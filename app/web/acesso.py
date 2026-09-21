"""Entrar no Jarvis com um código enviado ao e-mail corporativo.

Só entra quem lê uma caixa @easelabs.com.br. Isso restringe o app à empresa
sem depender de ninguém de fora do BI: quem sai da Ease perde o e-mail, e com
ele o acesso. Não há senha para vazar, reusar ou esquecer.

As regras de segurança, e por que cada uma existe:

- o código tem 6 dígitos, vale 10 minutos e só entra uma vez;
- são 5 tentativas por código; errou a quinta, o código morre;
- pedir um código novo anula o anterior do mesmo e-mail;
- no máximo 5 códigos por e-mail e 20 por IP por hora, para ninguém usar o
  Jarvis para encher a caixa de um colega (nem a nossa conta de envio de
  cair em lista de spam);
- o banco guarda um HMAC do código, não o código;
- usuário desativado no Admin recebe a mesma resposta de quem está ativo,
  mas nenhum e-mail sai — a tela não conta quem tem acesso.
"""

import hashlib
import hmac
import logging
import math
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from web.models import CodigoDeAcesso

logger = logging.getLogger(__name__)

DIGITOS = 6
VALIDADE = timedelta(minutes=10)
MAX_TENTATIVAS = 5
MAX_POR_EMAIL_HORA = 5
MAX_POR_IP_HORA = 20
# Tempo mínimo entre dois pedidos para o mesmo e-mail. A tela mostra a
# contagem; sem isto, dois cliques em "reenviar" anulavam o código que ainda
# estava a caminho.
INTERVALO_REENVIO = timedelta(seconds=60)

IMAGENS = Path(__file__).resolve().parent / "static" / "web" / "email"


def normalizar_email(texto: str) -> str | None:
    """O e-mail em minúsculas, ou None se não for exatamente do domínio.

    Exatamente: `x@easelabs.com.br` passa; `x@easelabs.com.br.golpe.com`,
    `x@sub.easelabs.com.br` e `x@easelabs.com` não."""
    email = (texto or "").strip().lower()
    dominio = re.escape(settings.DOMINIO_DE_ACESSO)
    if not re.fullmatch(rf"[a-z0-9._%+\-]+@{dominio}", email):
        return None
    return email


def _hash(email: str, codigo: str) -> str:
    chave = settings.SECRET_KEY.encode()
    return hmac.new(chave, f"{email}:{codigo}".encode(), hashlib.sha256).hexdigest()


def _gerar_codigo() -> str:
    return f"{secrets.randbelow(10 ** DIGITOS):0{DIGITOS}d}"


@dataclass(frozen=True)
class Pedido:
    """Resultado de um pedido de código.

    `situacao`: "enviado" | "limite" | "aguarde" | "falha_envio". Usuário
    desativado também devolve "enviado" — de propósito, ver o módulo."""

    situacao: str
    aguarde_segundos: int = 0


def solicitar_codigo(email: str, ip: str | None = None, navegador: str = "") -> Pedido:
    agora = timezone.now()
    uma_hora = agora - timedelta(hours=1)

    ultimo = CodigoDeAcesso.objects.filter(email=email).first()
    if ultimo and agora - ultimo.criado_em < INTERVALO_REENVIO:
        falta = INTERVALO_REENVIO - (agora - ultimo.criado_em)
        # Arredonda para cima, e não `int() + 1`: com os dois pedidos no mesmo
        # tique do relógio a falta é 60,0 exatos, e `int() + 1` mostrava 61.
        return Pedido("aguarde", aguarde_segundos=math.ceil(falta.total_seconds()))

    if CodigoDeAcesso.objects.filter(email=email, criado_em__gte=uma_hora).count() >= MAX_POR_EMAIL_HORA:
        return Pedido("limite")
    if ip and CodigoDeAcesso.objects.filter(ip=ip, criado_em__gte=uma_hora).count() >= MAX_POR_IP_HORA:
        return Pedido("limite")

    usuario = get_user_model().objects.filter(email__iexact=email).first()
    if usuario is not None and not usuario.is_active:
        # Mesma resposta de quem está ativo, e nada sai. Registrado para a
        # trilha mostrar a tentativa.
        logger.info("pedido de código para usuário desativado: %s", email)
        return Pedido("enviado")

    codigo = _gerar_codigo()
    with transaction.atomic():
        CodigoDeAcesso.objects.filter(email=email, usado_em__isnull=True, anulado_em__isnull=True).update(
            anulado_em=agora
        )
        registro = CodigoDeAcesso.objects.create(
            email=email,
            codigo_hash=_hash(email, codigo),
            expira_em=agora + VALIDADE,
            ip=ip,
            navegador=(navegador or "")[:200],
        )

    if not enviar_email_do_codigo(email, codigo):
        # Código que não chegou não pode ficar valendo, nem contar no limite
        # de reenvio como se tivesse ido.
        registro.anulado_em = timezone.now()
        registro.save(update_fields=["anulado_em"])
        return Pedido("falha_envio")
    return Pedido("enviado")


def verificar_codigo(email: str, codigo: str):
    """O usuário, se o código bate; None em qualquer outro caso.

    Sem distinguir expirado, errado ou inexistente: a tela diz a mesma coisa
    nos três, e quem tenta adivinhar não aprende nada."""
    codigo = re.sub(r"\D", "", codigo or "")
    if len(codigo) != DIGITOS:
        return None

    agora = timezone.now()
    with transaction.atomic():
        registro = (
            CodigoDeAcesso.objects.select_for_update()
            .filter(email=email, usado_em__isnull=True, anulado_em__isnull=True, expira_em__gt=agora)
            .first()
        )
        if registro is None:
            return None

        if not hmac.compare_digest(registro.codigo_hash, _hash(email, codigo)):
            registro.tentativas += 1
            campos = ["tentativas"]
            if registro.tentativas >= MAX_TENTATIVAS:
                registro.anulado_em = agora
                campos.append("anulado_em")
            registro.save(update_fields=campos)
            return None

        usuario = usuario_do_email(email)
        if usuario is None or not usuario.is_active:
            return None
        registro.usado_em = agora
        registro.save(update_fields=["usado_em"])
        return usuario


def _nome_do_email(email: str) -> tuple[str, str]:
    partes = [p for p in re.split(r"[._\-]+", email.split("@")[0]) if p]
    nomes = [p.capitalize() for p in partes]
    if not nomes:
        return "", ""
    return nomes[0], " ".join(nomes[1:])


def usuario_do_email(email: str):
    """Acha ou cadastra o usuário do e-mail.

    Ordem da busca:
    1. pelo e-mail;
    2. pelo usuário antigo sem e-mail com o mesmo nome — `rubens.filho@`
       vira `rubens_filho`, que é como os administradores foram criados antes
       do login por código (infra/app-db/usuarios_iniciais.csv). Sem isto
       eles entrariam como usuários novos e perderiam o papel de admin. Só
       casa com quem está SEM e-mail: um e-mail já gravado nunca é trocado;
    3. cadastro novo, sem senha utilizável.
    """
    User = get_user_model()
    usuario = User.objects.filter(email__iexact=email).first()
    if usuario is not None:
        return usuario

    nome_de_usuario = email.split("@")[0].replace(".", "_")
    antigo = User.objects.filter(username__iexact=nome_de_usuario, email="").first()
    if antigo is not None:
        antigo.email = email
        antigo.save(update_fields=["email"])
        logger.info("e-mail vinculado ao usuário existente %s", antigo.username)
        return antigo

    if User.objects.filter(username__iexact=nome_de_usuario).exists():
        nome_de_usuario = email  # nome já tomado por outra pessoa
    primeiro, sobrenome = _nome_do_email(email)
    usuario = User(username=nome_de_usuario, email=email, first_name=primeiro, last_name=sobrenome)
    usuario.set_unusable_password()
    usuario.save()
    logger.info("usuário cadastrado no primeiro acesso: %s", email)
    return usuario


def enviar_email_do_codigo(email: str, codigo: str) -> bool:
    """Manda o código. Nunca propaga exceção — mesma regra do Cockpit: falha
    de SMTP é registrada e vira aviso na tela, não um erro 500."""
    minutos = int(VALIDADE.total_seconds() // 60)
    contexto = {"codigo": codigo, "email": email, "minutos": minutos}
    assunto = "Seu código de acesso ao Jarvis"
    texto = render_to_string("web/email/codigo.txt", contexto)
    html = render_to_string("web/email/codigo.html", contexto)

    try:
        mensagem = EmailMultiAlternatives(assunto, texto, to=[email])
        mensagem.attach_alternative(html, "text/html")
        # As imagens vão dentro do e-mail (Content-ID), não por link: o
        # Outlook bloqueia imagem externa por padrão, e o Jarvis nem precisa
        # estar publicado para o e-mail sair bonito.
        mensagem.mixed_subtype = "related"
        for arquivo, cid in (("logo@2x.png", "logo"), ("jarvis@2x.png", "jarvis")):
            caminho = IMAGENS / arquivo
            if caminho.exists():
                imagem = MIMEImage(caminho.read_bytes(), _subtype="png")
                imagem.add_header("Content-ID", f"<{cid}>")
                imagem.add_header("Content-Disposition", "inline", filename=arquivo)
                mensagem.attach(imagem)
        mensagem.send()
    except Exception:
        logger.exception("falha ao enviar o código de acesso para %s", email)
        return False
    return True
