"""Cria e atualiza os usuários do Jarvis a partir do cadastro da empresa.

O acesso é por usuário e senha do Django (ADR-0011). A lista de quem pode
entrar vem de um arquivo (`--arquivo`), que é o caminho padrão: por decisão
de 2026-09-18 o projeto não depende de nenhum schema de outro sistema, e o
cadastro do Jarvis é o próprio `auth_user`, administrado pelo Admin do Django.

Existe também `--do-banco`, que lê `trade_fv.usuario`. Fica desligado por
padrão e só funciona se alguém conceder SELECT naquela tabela — hoje ninguém
tem, e não vamos pedir.

Duas garantias que o comando precisa dar, porque ele mexe em acesso:

1. **Não toca em senha de quem já existe.** Rodar de novo nunca derruba
   ninguém nem reabre conta fechada à mão.
2. **Só desativa quem ele mesmo criou.** Os sincronizados entram no grupo
   `cadastro-empresa`; contas criadas fora dele (a `demo`, um acesso
   temporário) não são desativadas nem que sumam da origem.

A consulta não passa pelo validador de SQL: ele existe para consulta escrita
por IA (ADR-0009), e esta é fixa e revisada. A conexão é a mesma de leitura
do chatbot, então continua valendo somente leitura (ADR-0008).
"""

import csv
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from datasource.executors.base import QueryExecutionError
from datasource.executors.factory import get_configured_executor

GRUPO = "cadastro-empresa"

CONSULTA = """
SELECT usuario, nome, email, role
FROM trade_fv.usuario
WHERE role = %s
ORDER BY usuario
"""
# O executor não aceita parâmetros: a consulta é montada aqui, com o papel
# vindo de uma lista fechada, nunca do que o usuário digitar.
PAPEIS = {"admin", "gestor", "usuario"}


class Command(BaseCommand):
    help = "Sincroniza os usuários do Jarvis com o cadastro da empresa (trade_fv.usuario)."

    def add_arguments(self, parser):
        parser.add_argument("--papel", default="admin", help=f"papel na origem: {', '.join(sorted(PAPEIS))}")
        parser.add_argument("--arquivo", help="CSV com usuario,nome,email,role (caminho padrão)")
        parser.add_argument("--do-banco", action="store_true",
                            help="lê trade_fv.usuario em vez do arquivo; exige SELECT naquela tabela")
        parser.add_argument("--desativar-ausentes", action="store_true",
                            help="desativa quem saiu da origem (só afeta quem este comando criou)")
        parser.add_argument("--simular", action="store_true", help="mostra o que faria, sem gravar")

    def handle(self, *args, **opcoes):
        papel = opcoes["papel"]
        if papel not in PAPEIS:
            raise CommandError(f"papel desconhecido: {papel}")

        if opcoes["arquivo"]:
            pessoas = self._do_arquivo(opcoes["arquivo"], papel)
        elif opcoes["do_banco"]:
            pessoas = self._do_banco(papel)
        else:
            raise CommandError("informe --arquivo com a lista (ou --do-banco, se houver acesso a trade_fv.usuario)")
        if not pessoas:
            raise CommandError("a origem não devolveu ninguém; nada foi alterado")

        if opcoes["simular"]:
            self.stdout.write(f"{len(pessoas)} pessoa(s) na origem (papel {papel}):")
            for p in pessoas:
                self.stdout.write(f"  {p['usuario']:<20} {p['nome']}")
            return

        criados, atualizados = self._gravar(pessoas)
        desativados = self._desativar_ausentes(pessoas) if opcoes["desativar_ausentes"] else 0

        self.stdout.write(self.style.SUCCESS(
            f"{criados} criado(s), {atualizados} atualizado(s), {desativados} desativado(s)."
        ))
        if criados:
            self.stdout.write(
                "Os novos nascem sem senha utilizável: ninguém entra até definir uma.\n"
                "  uv run python app/manage.py changepassword <usuario>"
            )

    # ---- origens ---------------------------------------------------------
    def _do_banco(self, papel):
        try:
            resultado = get_configured_executor().run(CONSULTA % f"'{papel}'", max_rows=5000)
        except QueryExecutionError as erro:
            raise CommandError(
                f"não consegui ler trade_fv.usuario: {erro}\n"
                "O usuário de leitura precisa de GRANT USAGE no schema trade_fv e "
                "GRANT SELECT na tabela usuario. Enquanto isso, use --arquivo."
            ) from erro
        colunas = list(resultado.columns)
        return [dict(zip(colunas, linha)) for linha in resultado.rows]

    def _do_arquivo(self, caminho, papel):
        arquivo = Path(caminho)
        if not arquivo.exists():
            raise CommandError(f"arquivo não encontrado: {arquivo}")
        with arquivo.open(encoding="utf-8-sig", newline="") as f:
            leitor = csv.DictReader(f)
            # As colunas saem do cabeçalho, não da primeira linha: um arquivo
            # só com cabeçalho é "origem vazia", que é outro erro — e é o que
            # precisa impedir uma desativação em massa logo abaixo.
            faltando = {"usuario", "nome"} - set(leitor.fieldnames or [])
            if faltando:
                raise CommandError(f"o CSV precisa das colunas {sorted(faltando)}")
            linhas = list(leitor)
        return [l for l in linhas if (l.get("role") or papel).strip() == papel]

    # ---- gravação --------------------------------------------------------
    @transaction.atomic
    def _gravar(self, pessoas):
        User = get_user_model()
        grupo, _ = Group.objects.get_or_create(name=GRUPO)
        criados = atualizados = 0

        for pessoa in pessoas:
            username = (pessoa.get("usuario") or "").strip()
            if not username:
                continue
            nome = (pessoa.get("nome") or "").strip()
            primeiro, _, sobrenome = nome.partition(" ")
            campos = {
                "first_name": primeiro[:150],
                "last_name": sobrenome[:150],
                "email": (pessoa.get("email") or "").strip(),
                # Papel admin na origem = equipe de BI: vê custo e tokens na
                # fonte da resposta e entra no Admin do Django.
                "is_staff": True,
            }
            usuario = User.objects.filter(username=username).first()
            if usuario is None:
                usuario = User(username=username, **campos)
                usuario.set_unusable_password()
                usuario.save()
                criados += 1
            else:
                mudou = [c for c, v in campos.items() if getattr(usuario, c) != v]
                if mudou:
                    for c, v in campos.items():
                        setattr(usuario, c, v)
                    usuario.save(update_fields=mudou)
                    atualizados += 1
            usuario.groups.add(grupo)
        return criados, atualizados

    def _desativar_ausentes(self, pessoas):
        User = get_user_model()
        presentes = {(p.get("usuario") or "").strip() for p in pessoas}
        ausentes = User.objects.filter(groups__name=GRUPO, is_active=True).exclude(username__in=presentes)
        return ausentes.update(is_active=False)
