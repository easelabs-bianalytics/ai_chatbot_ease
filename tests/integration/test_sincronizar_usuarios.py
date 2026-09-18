"""Sincronização dos usuários com o cadastro da empresa.

Comando que mexe em acesso: o que se fixa aqui é que rodar de novo não
derruba ninguém, que senha de quem já existe nunca é tocada e que conta
criada fora do comando (a `demo`, um acesso temporário) não é desativada
por engano.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from datasource.executors.base import QueryExecutionError

pytestmark = pytest.mark.django_db

CSV = """usuario,nome,email,role
paulo_lima,Paulo Lima,,admin
fernando_franco,Fernando Franco,fernando.franco@easelabs.com.br,admin
joana_reis,Joana Reis,joana@easelabs.com.br,usuario
"""


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "usuarios.csv"
    caminho.write_text(CSV, encoding="utf-8")
    return str(caminho)


def _sincronizar(arquivo, **opcoes):
    call_command("sincronizar_usuarios", arquivo=arquivo, **opcoes)


def test_cria_os_admins_sem_senha_utilizavel(arquivo):
    """Ninguém entra só por existir no cadastro: a senha é definida depois,
    fora deste comando."""
    _sincronizar(arquivo)

    User = get_user_model()
    paulo = User.objects.get(username="paulo_lima")
    assert paulo.first_name == "Paulo" and paulo.last_name == "Lima"
    assert paulo.is_staff is True and paulo.is_superuser is False
    assert paulo.has_usable_password() is False
    assert paulo.groups.filter(name="cadastro-empresa").exists()
    assert User.objects.get(username="fernando_franco").email == "fernando.franco@easelabs.com.br"


def test_so_traz_o_papel_pedido(arquivo):
    """A Joana é `usuario` na origem: não entra numa sincronização de admins."""
    _sincronizar(arquivo)

    assert not get_user_model().objects.filter(username="joana_reis").exists()


def test_rodar_de_novo_nao_muda_nada(arquivo):
    _sincronizar(arquivo)
    antes = get_user_model().objects.get(username="paulo_lima")
    carimbo = antes.date_joined

    _sincronizar(arquivo)

    depois = get_user_model().objects.get(username="paulo_lima")
    assert get_user_model().objects.count() == 2
    assert depois.date_joined == carimbo


def test_atualiza_nome_e_email_sem_tocar_na_senha(arquivo, tmp_path):
    _sincronizar(arquivo)
    User = get_user_model()
    paulo = User.objects.get(username="paulo_lima")
    paulo.set_password("a-senha-que-ele-escolheu")
    paulo.save()

    novo = tmp_path / "novo.csv"
    novo.write_text("usuario,nome,email,role\npaulo_lima,Paulo Lima Neto,paulo@easelabs.com.br,admin\n",
                    encoding="utf-8")
    _sincronizar(str(novo))

    paulo.refresh_from_db()
    assert paulo.last_name == "Lima Neto"
    assert paulo.email == "paulo@easelabs.com.br"
    assert paulo.check_password("a-senha-que-ele-escolheu")


def test_desativa_so_quem_o_comando_criou(arquivo, tmp_path, django_user_model):
    """A `demo` não está no cadastro da empresa e não pode cair junto."""
    demo = django_user_model.objects.create_user("demo", password="x")
    _sincronizar(arquivo)

    menor = tmp_path / "menor.csv"
    menor.write_text("usuario,nome,email,role\npaulo_lima,Paulo Lima,,admin\n", encoding="utf-8")
    _sincronizar(str(menor), desativar_ausentes=True)

    demo.refresh_from_db()
    assert demo.is_active is True
    assert django_user_model.objects.get(username="fernando_franco").is_active is False
    assert django_user_model.objects.get(username="paulo_lima").is_active is True


def test_sem_a_bandeira_ninguem_e_desativado(arquivo, tmp_path):
    _sincronizar(arquivo)

    menor = tmp_path / "menor.csv"
    menor.write_text("usuario,nome,email,role\npaulo_lima,Paulo Lima,,admin\n", encoding="utf-8")
    _sincronizar(str(menor))

    assert get_user_model().objects.get(username="fernando_franco").is_active is True


def test_origem_vazia_nao_apaga_ninguem(tmp_path, arquivo):
    """Um erro na origem que devolva zero linha não pode virar 'desative
    todo mundo'."""
    _sincronizar(arquivo)
    vazio = tmp_path / "vazio.csv"
    vazio.write_text("usuario,nome,email,role\n", encoding="utf-8")

    with pytest.raises(CommandError, match="não devolveu ninguém"):
        _sincronizar(str(vazio), desativar_ausentes=True)

    assert get_user_model().objects.filter(is_active=True).count() == 2


def test_sem_permissao_no_banco_o_erro_diz_o_que_pedir(monkeypatch):
    """Hoje o usuário de leitura não enxerga trade_fv.usuario (2026-09-18):
    o comando precisa dizer qual GRANT falta, não só 'permission denied'."""
    class Negando:
        def run(self, sql, max_rows=None):
            raise QueryExecutionError("permission denied for table usuario")

    monkeypatch.setattr(
        "web.management.commands.sincronizar_usuarios.get_configured_executor", lambda: Negando()
    )

    with pytest.raises(CommandError, match="GRANT SELECT"):
        call_command("sincronizar_usuarios", do_banco=True)


def test_papel_desconhecido_para_antes_de_consultar():
    with pytest.raises(CommandError, match="papel desconhecido"):
        call_command("sincronizar_usuarios", papel="root")


def test_sem_origem_o_comando_explica_o_que_falta():
    """O padrão é o arquivo: o projeto não depende de schema de outro
    sistema (decisão de 2026-09-18)."""
    with pytest.raises(CommandError, match="--arquivo"):
        call_command("sincronizar_usuarios")
