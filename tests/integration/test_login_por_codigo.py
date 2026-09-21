"""Entrar com código enviado ao e-mail corporativo (decisão de 2026-09-21).

É a porta do dado de negócio da empresa inteira: só entra quem lê uma caixa
@easelabs.com.br. Cada teste aqui fixa uma das regras de web/acesso.py e diz
o que ela impede.
"""

import json
import re
from datetime import timedelta

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone

from web.acesso import MAX_POR_EMAIL_HORA, MAX_TENTATIVAS, normalizar_email
from web.models import CodigoDeAcesso

pytestmark = pytest.mark.django_db

EMAIL = "fernando.franco@easelabs.com.br"


def _csrf(cliente) -> str:
    cliente.get("/api/auth/sessao/")
    return cliente.cookies["csrftoken"].value


def _post(cliente, url, corpo, **extra):
    return cliente.post(
        url, data=json.dumps(corpo), content_type="application/json",
        HTTP_X_CSRFTOKEN=_csrf(cliente), **extra,
    )


def _pedir(cliente, email=EMAIL, **extra):
    return _post(cliente, "/api/auth/codigo/", {"email": email}, **extra)


def _entrar(cliente, codigo, email=EMAIL):
    return _post(cliente, "/api/auth/entrar/", {"email": email, "codigo": codigo})


def _codigo_do_ultimo_email() -> str:
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def _liberar_reenvio():
    """Empurra os pedidos para trás no tempo, para o próximo não esbarrar no
    intervalo mínimo de reenvio."""
    CodigoDeAcesso.objects.update(criado_em=timezone.now() - timedelta(minutes=2))


@pytest.fixture
def cliente():
    return Client(enforce_csrf_checks=True)


# --- domínio --------------------------------------------------------------


@pytest.mark.parametrize("texto", [
    "fernando.franco@easelabs.com.br",
    "  Fernando.Franco@EASELABS.com.br ",
])
def test_aceita_so_o_dominio_da_empresa(texto):
    assert normalizar_email(texto) == "fernando.franco@easelabs.com.br"


@pytest.mark.parametrize("texto", [
    "fernando@gmail.com",
    "fernando@easelabs.com",
    "fernando@sub.easelabs.com.br",
    # O domínio da empresa no meio do endereço de outro: o golpe clássico.
    "fernando@easelabs.com.br.golpe.com",
    "fernando@easelabs.com.br@golpe.com",
    "easelabs.com.br",
    "",
])
def test_recusa_o_que_nao_e_exatamente_do_dominio(texto):
    assert normalizar_email(texto) is None


def test_email_de_fora_nao_recebe_codigo(cliente):
    resposta = _pedir(cliente, "fernando@gmail.com")

    assert resposta.status_code == 400
    assert "@easelabs.com.br" in resposta.json()["error"]
    assert mail.outbox == []
    assert CodigoDeAcesso.objects.count() == 0


def test_pedir_codigo_sem_csrf_e_recusado():
    """Sem a checagem, qualquer site poderia disparar códigos em nome de
    quem estivesse com o Jarvis aberto."""
    resposta = Client(enforce_csrf_checks=True).post(
        "/api/auth/codigo/", data=json.dumps({"email": EMAIL}), content_type="application/json",
    )

    assert resposta.status_code == 403
    assert mail.outbox == []


# --- o e-mail -------------------------------------------------------------


def test_codigo_chega_por_email_com_texto_html_e_imagens(cliente):
    resposta = _pedir(cliente)

    assert resposta.status_code == 200
    assert resposta.json() == {"enviado": True, "email": EMAIL, "reenviar_em": 60}
    assert len(mail.outbox) == 1
    enviado = mail.outbox[0]
    codigo = _codigo_do_ultimo_email()
    assert enviado.to == [EMAIL]
    assert codigo in enviado.alternatives[0][0]
    # As imagens vão dentro do e-mail: o Outlook bloqueia imagem externa.
    ids = {parte["Content-ID"] for parte in enviado.attachments if hasattr(parte, "get")}
    assert {"<logo>", "<jarvis>"} <= ids


def test_nada_do_template_vaza_no_email(cliente):
    """Em 2026-09-21 um comentário de template de várias linhas (`{# #}` só
    vale numa) aparecia como texto no meio do e-mail e da tela de login."""
    _pedir(cliente)
    enviado = mail.outbox[0]

    for corpo in (enviado.body, enviado.alternatives[0][0]):
        assert "{#" not in corpo and "#}" not in corpo and "{%" not in corpo


def test_nada_do_template_vaza_na_tela_de_login():
    pagina = Client().get("/").content.decode()

    assert "{#" not in pagina and "{%" not in pagina


def test_codigo_nao_vai_no_assunto(cliente):
    """O assunto aparece na tela bloqueada do celular."""
    _pedir(cliente)

    assert not re.search(r"\d{6}", mail.outbox[0].subject)


def test_banco_guarda_o_hash_e_nunca_o_codigo(cliente):
    """Quem lê o banco não pode entrar com o que leu."""
    _pedir(cliente)
    codigo = _codigo_do_ultimo_email()

    registro = CodigoDeAcesso.objects.get()
    assert codigo not in registro.codigo_hash
    assert len(registro.codigo_hash) == 64


def test_falha_de_envio_avisa_e_o_codigo_nao_fica_valendo(cliente, monkeypatch):
    monkeypatch.setattr("web.acesso.enviar_email_do_codigo", lambda email, codigo: False)

    resposta = _pedir(cliente)

    assert resposta.status_code == 503
    assert CodigoDeAcesso.objects.get().anulado_em is not None


# --- entrar ---------------------------------------------------------------


def test_codigo_certo_abre_a_sessao_e_cadastra_o_usuario(cliente, django_user_model):
    _pedir(cliente)

    resposta = _entrar(cliente, _codigo_do_ultimo_email())

    assert resposta.status_code == 200
    assert resposta.json()["usuario"]["email"] == EMAIL
    assert resposta.json()["usuario"]["nome"] == "Fernando Franco"
    assert cliente.get("/api/auth/sessao/").json()["autenticado"] is True
    usuario = django_user_model.objects.get(email=EMAIL)
    assert usuario.username == "fernando_franco"
    assert not usuario.has_usable_password()
    assert usuario.last_login is not None


def test_codigo_colado_com_espaco_tambem_entra(cliente):
    _pedir(cliente)
    codigo = _codigo_do_ultimo_email()

    assert _entrar(cliente, f"{codigo[:3]} {codigo[3:]}").status_code == 200


def test_codigo_so_entra_uma_vez(cliente):
    _pedir(cliente)
    codigo = _codigo_do_ultimo_email()
    _entrar(cliente, codigo)

    assert _entrar(Client(enforce_csrf_checks=True), codigo).status_code == 400


def test_codigo_expirado_nao_entra(cliente):
    _pedir(cliente)
    codigo = _codigo_do_ultimo_email()
    CodigoDeAcesso.objects.update(expira_em=timezone.now() - timedelta(seconds=1))

    assert _entrar(cliente, codigo).status_code == 400


def test_codigo_de_um_email_nao_serve_para_outro(cliente):
    _pedir(cliente)
    codigo = _codigo_do_ultimo_email()

    assert _entrar(cliente, codigo, email="outra.pessoa@easelabs.com.br").status_code == 400


def test_erro_nao_diz_se_o_codigo_expirou_ou_esta_errado(cliente):
    """Dizer qual dos dois ensinaria algo a quem tenta adivinhar."""
    _pedir(cliente)
    errado = _entrar(cliente, "000000").json()["error"]
    CodigoDeAcesso.objects.update(expira_em=timezone.now() - timedelta(seconds=1))
    expirado = _entrar(cliente, _codigo_do_ultimo_email()).json()["error"]

    assert errado == expirado


def test_tentativas_demais_matam_o_codigo(cliente):
    """Seis dígitos são um milhão de combinações; sem limite, dá para testar
    todas dentro dos 10 minutos."""
    _pedir(cliente)
    codigo = _codigo_do_ultimo_email()
    errado = "000000" if codigo != "000000" else "111111"

    for _ in range(MAX_TENTATIVAS):
        _entrar(cliente, errado)

    assert _entrar(cliente, codigo).status_code == 400
    assert CodigoDeAcesso.objects.get().anulado_em is not None


def test_codigo_novo_anula_o_anterior(cliente, monkeypatch):
    codigos = iter(["111111", "222222"])
    monkeypatch.setattr("web.acesso._gerar_codigo", lambda: next(codigos))
    _pedir(cliente)
    _liberar_reenvio()
    _pedir(cliente)

    assert _entrar(cliente, "111111").status_code == 400
    assert _entrar(cliente, "222222").status_code == 200


# --- limites --------------------------------------------------------------


def test_reenvio_tem_intervalo_minimo(cliente):
    """Dois cliques em "reenviar" anulavam o código que ainda estava a
    caminho, e a pessoa digitava um código que já não valia."""
    _pedir(cliente)

    resposta = _pedir(cliente)

    assert resposta.status_code == 429
    assert 0 < resposta.json()["reenviar_em"] <= 60
    assert len(mail.outbox) == 1


def test_limite_de_codigos_por_email_na_hora(cliente):
    """Sem ele, dava para usar o Jarvis para encher a caixa de um colega — e
    a nossa conta de envio acabaria em lista de spam."""
    for _ in range(MAX_POR_EMAIL_HORA):
        _pedir(cliente)
        _liberar_reenvio()

    resposta = _pedir(cliente)

    assert resposta.status_code == 429
    assert len(mail.outbox) == MAX_POR_EMAIL_HORA


def test_ip_atras_do_balanceador_vem_do_ultimo_encaminhado(cliente):
    """O primeiro endereço do X-Forwarded-For o próprio navegador inventa; o
    último é o que o ALB escreveu. Usar o primeiro deixaria qualquer um
    escapar do limite por IP trocando o cabeçalho."""
    _pedir(cliente, HTTP_X_FORWARDED_FOR="1.2.3.4, 200.10.20.30")

    assert CodigoDeAcesso.objects.get().ip == "200.10.20.30"


# --- quem é quem ----------------------------------------------------------


def test_usuario_desativado_nao_recebe_codigo_mas_a_tela_nao_conta(cliente, django_user_model):
    """A resposta igual à de quem está ativo não deixa ninguém descobrir, pela
    tela, quem teve o acesso cortado."""
    django_user_model.objects.create_user("fernando_franco", email=EMAIL, is_active=False)

    resposta = _pedir(cliente)

    assert resposta.status_code == 200
    assert resposta.json()["enviado"] is True
    assert mail.outbox == []


def test_administrador_antigo_sem_email_e_reconhecido(cliente, django_user_model):
    """Os administradores foram criados antes do login por código, a maioria
    sem e-mail (infra/app-db/usuarios_iniciais.csv). Sem este vínculo, eles
    entrariam como usuários novos e perderiam o papel de admin."""
    antigo = django_user_model.objects.create_user("rubens_filho", is_staff=True)
    _pedir(cliente, "rubens.filho@easelabs.com.br")

    resposta = _entrar(cliente, _codigo_do_ultimo_email(), email="rubens.filho@easelabs.com.br")

    assert resposta.json()["usuario"]["equipe"] is True
    antigo.refresh_from_db()
    assert antigo.email == "rubens.filho@easelabs.com.br"
    assert django_user_model.objects.count() == 1


def test_email_ja_gravado_nunca_e_trocado(cliente, django_user_model):
    """O vínculo por nome só vale para quem está sem e-mail. Quem já tem um
    não pode ser "reivindicado" por outro endereço parecido."""
    dono = django_user_model.objects.create_user(
        "rubens_filho", email="rubens.filho.antigo@easelabs.com.br", is_staff=True
    )
    _pedir(cliente, "rubens.filho@easelabs.com.br")

    resposta = _entrar(cliente, _codigo_do_ultimo_email(), email="rubens.filho@easelabs.com.br")

    assert resposta.json()["usuario"]["equipe"] is False
    dono.refresh_from_db()
    assert dono.email == "rubens.filho.antigo@easelabs.com.br"


# --- as outras portas -----------------------------------------------------


def test_tela_de_senha_do_admin_leva_ao_login_por_codigo():
    """O Admin tem tela de senha própria: deixada aberta, seria uma entrada
    sem e-mail da empresa."""
    resposta = Client().get("/admin/login/?next=/admin/")

    assert resposta.status_code == 302
    assert resposta["Location"] == "/?proximo=/admin/"


def test_quem_entrou_pelo_codigo_abre_o_admin_se_for_da_equipe(cliente, django_user_model):
    django_user_model.objects.create_user("fernando_franco", email=EMAIL, is_staff=True)
    _pedir(cliente)
    _entrar(cliente, _codigo_do_ultimo_email())

    assert cliente.get("/admin/").status_code == 200


def test_contagem_de_reenvio_nunca_passa_de_60_segundos(monkeypatch):
    """Com os dois pedidos no mesmo tique do relógio, a falta era 60,0 exatos
    e `int() + 1` mostrava 61 s na tela (achado em 2026-09-21, teste que
    falhava de vez em quando no Windows)."""
    from django.utils import timezone

    from web import acesso
    from web.models import CodigoDeAcesso

    congelado = timezone.now()
    monkeypatch.setattr(acesso.timezone, "now", lambda: congelado)
    # auto_now_add usa o mesmo `timezone.now` congelado: os dois pedidos
    # caem no mesmo instante, que é o caso que dava 61.
    CodigoDeAcesso.objects.create(
        email="ana@easelabs.com.br", codigo_hash="x", expira_em=congelado + acesso.VALIDADE
    )

    pedido = acesso.solicitar_codigo("ana@easelabs.com.br", ip="10.0.0.1")

    assert pedido.aguarde_segundos == 60
