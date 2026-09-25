"""O Jarvis no WhatsApp, do evento à resposta entregue (ADR-0028).

Nenhum teste aqui fala com a Evolution: o cliente é o fake, que guarda o que
teria saído. O que se fixa:

- a trava do cadastro — o número respondeu em grupos reais por engano na
  referência (2026-09-04), e aqui só fala quem está liberado;
- no grupo, só quando chamado;
- a mesma resposta do chat web, na forma do WhatsApp (texto, gráfico em
  imagem, planilha, continuações), e a mesma auditoria;
- 👍/👎 por reação, "parar", "nova conversa", "fonte" e escolha por número.
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from ai_orchestrator import progresso
from ai_orchestrator.models import AIReply
from conversations.models import Conversation
from datasource.executors.fake import FakeQueryExecutor, make_result
from messaging.models import Avaliacao, Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from whatsapp import aviso, config, servicos
from whatsapp.cliente import ClienteFake
from whatsapp.models import ContatoWhatsApp, EnvioWhatsApp, GrupoWhatsApp

pytestmark = pytest.mark.django_db

PAULO = "5511977776666"
JARVIS = "5511900001111"
GRUPO = "120363000000001@g.us"
MESES = make_result(("mes", "und"), [("2026-07", 761), ("2026-08", 777)])


@pytest.fixture(autouse=True)
def numero_do_jarvis(monkeypatch):
    monkeypatch.setenv("WHATSAPP_NUMERO_JARVIS", JARVIS)
    cache.clear()


@pytest.fixture
def paulo(django_user_model):
    user = django_user_model.objects.create_user("paulo.lima@easelabs.com.br", email="paulo.lima@easelabs.com.br")
    ContatoWhatsApp.objects.create(numero="+55 (11) 97777-6666", user=user)
    return user


@pytest.fixture
def grupo():
    return GrupoWhatsApp.objects.create(jid=GRUPO, nome="Comercial Nordeste")


@pytest.fixture
def cliente():
    return ClienteFake()


def _evento(texto=None, jid=f"{PAULO}@s.whatsapp.net", ident="M1", message=None, **chave):
    return {"event": "messages.upsert", "instance": "jarvis", "data": {
        "key": {"remoteJid": jid, "fromMe": False, "id": ident, **chave},
        "pushName": "Paulo", "message": message or {"conversation": texto},
    }}


def _no_grupo(texto, ident="G1", mencao=True, **extra):
    contexto = {"mentionedJid": [f"{JARVIS}@s.whatsapp.net"]} if mencao else {}
    contexto.update(extra)
    return _evento(jid=GRUPO, ident=ident, participant=f"{PAULO}@s.whatsapp.net",
                   message={"extendedTextMessage": {"text": texto, "contextInfo": contexto}})


def _receber(payload, cliente, planos=(), respostas=(), resultados=(MESES,)):
    provider = ScriptedAIProvider(list(planos), list(respostas))
    resultado = servicos.receber(payload, cliente=cliente, provider=provider,
                                 executor=FakeQueryExecutor(list(resultados)))
    return resultado, provider


def _pergunta_respondida(cliente, texto="vendas por mês", ident="M1", **resposta_campos):
    return _receber(_evento(texto, ident=ident), cliente, [plano(entendimento="Unidades Ease por mês em 2026")],
                    [resposta("Foram 777 unidades em ago/2026.", **resposta_campos)])


# ------------------------------------------------------------ quem pode falar


def test_numero_liberado_recebe_a_mesma_resposta_do_chat_web(paulo, cliente):
    resultado, provider = _pergunta_respondida(cliente)

    assert resultado == "respondida"
    conversa = Conversation.objects.get()
    assert (conversa.user, conversa.canal, conversa.whatsapp_jid) == (paulo, "whatsapp", f"{PAULO}@s.whatsapp.net")
    pergunta = Message.objects.get(direction="in")
    assert (pergunta.client_message_id, pergunta.autor_externo) == ("M1", PAULO)
    # Mesma auditoria do chat web: plano, consulta e custo gravados.
    assert AIReply.objects.get(message=pergunta).decision == AIReply.Decision.ANSWERED
    textos = [e for e in cliente.enviados if e["tipo"] == "texto"]
    assert textos[-1]["texto"] == "Foram 777 unidades em ago/2026."
    saida = Message.objects.get(direction="out")
    assert saida.status == Message.Status.SENT
    assert EnvioWhatsApp.objects.filter(message=saida).exists()


def test_numero_nao_liberado_e_ignorado_sem_gastar_nada(cliente):
    resultado, provider = _receber(_evento("vendas"), cliente)

    assert resultado == "contato_nao_liberado"
    assert provider.plan_requests == [] and cliente.enviados == []
    assert not Message.objects.exists()


def test_numero_de_usuario_desativado_nao_fala(paulo, cliente):
    paulo.is_active = False
    paulo.save()

    assert _receber(_evento("vendas"), cliente)[0] == "contato_nao_liberado"


def test_grupo_nao_liberado_e_ignorado_mesmo_marcando(cliente):
    """O incidente da referência: um número conectado responde em todo grupo
    em que já estiver. Aqui só grupo cadastrado."""
    assert _receber(_no_grupo("@5511900001111 vendas"), cliente)[0] == "grupo_nao_liberado"
    assert cliente.enviados == []


def test_no_grupo_so_responde_quando_chamado(grupo, cliente):
    resultado, provider = _receber(_no_grupo("bom dia pessoal", mencao=False), cliente)

    assert resultado == "grupo_sem_mencao"
    assert provider.plan_requests == [] and not Message.objects.exists()


def test_grupo_liberado_qualquer_membro_chama_e_a_resposta_cita_a_pergunta(grupo, cliente):
    resultado, provider = _receber(_no_grupo(f"@{JARVIS} vendas por mês"), cliente,
                                   [plano()], [resposta("Foram 777 unidades em ago/2026.")])

    assert resultado == "respondida"
    assert provider.plan_requests[0].question == "vendas por mês"     # sem a menção
    conversa = Conversation.objects.get()
    assert conversa.user == grupo.usuario and conversa.whatsapp_jid == GRUPO
    assert Message.objects.get(direction="in").autor_nome == "Paulo"
    assert cliente.enviados[-1]["citar"] == "G1"


def test_responder_citando_o_jarvis_no_grupo_tambem_chama(grupo, cliente):
    _receber(_no_grupo(f"@{JARVIS} vendas por mês"), cliente, [plano()], [resposta("Foram 777 unidades em ago/2026.")])
    id_do_jarvis = cliente.enviados[-1]["id"]

    resultado, _ = _receber(_no_grupo("e em julho?", ident="G2", mencao=False, stanzaId=id_do_jarvis), cliente,
                            [plano()], [resposta("Foram 761 unidades em jul/2026.")])

    assert resultado == "respondida"


def test_cota_do_grupo_e_a_do_cadastro(grupo, cliente):
    grupo.limite_diario = 0
    grupo.save()

    _, provider = _receber(_no_grupo(f"@{JARVIS} vendas por mês"), cliente)

    assert provider.plan_requests == []
    assert AIReply.objects.get().rule == "limite_diario_da_pessoa"


# ------------------------------------------------------------ a forma da resposta


def test_grafico_vai_como_imagem_e_continuacoes_numeradas(paulo, cliente):
    _pergunta_respondida(
        cliente, chart={"tipo": "barras", "x": "mes", "series": ["und"], "titulo": "Unidades"},
        followups=("E por rede?", "E no Ceará?"),
    )

    tipos = [e["tipo"] for e in cliente.enviados]
    assert "image" in tipos
    imagem = next(e for e in cliente.enviados if e["tipo"] == "image")
    assert imagem["dados"][:4] == b"\x89PNG" and imagem["legenda"] == "Unidades"
    texto = next(e for e in reversed(cliente.enviados) if e["tipo"] == "texto")["texto"]
    assert "1. E por rede?" in texto and "2. E no Ceará?" in texto


def test_responder_com_o_numero_escolhe_a_continuacao(paulo, cliente):
    _pergunta_respondida(cliente, followups=("E por rede?",))

    _, provider = _receber(_evento("1", ident="M2"), cliente, [plano()], [resposta("Foram 777 unidades em ago/2026.")])

    assert provider.plan_requests[0].question == "E por rede?"


def test_pedido_de_planilha_manda_o_arquivo(paulo, cliente):
    _receber(_evento("vendas por mês em excel"), cliente, [plano(excel=True)],
             [resposta("A planilha tem 2 linhas.")], resultados=(MESES, MESES))

    documento = next(e for e in cliente.enviados if e["tipo"] == "document")
    assert documento["nome"].endswith(".xlsx") and documento["dados"][:2] == b"PK"


def test_evolution_fora_do_ar_marca_a_resposta_como_nao_entregue(paulo):
    """A resposta continua gravada e visível no chat web."""
    _pergunta_respondida(ClienteFake(falhar=True))

    saida = Message.objects.get(direction="out")
    assert saida.status == Message.Status.FAILED
    assert saida.content == "Foram 777 unidades em ago/2026."


# ------------------------------------------------------------ conversa e comandos


def test_mesmo_evento_duas_vezes_vira_uma_pergunta(paulo, cliente):
    _pergunta_respondida(cliente)
    resultado, provider = _receber(_evento("vendas por mês"), cliente)

    assert resultado == "repetida" and provider.plan_requests == []


def test_conversa_parada_ha_horas_abre_outra(paulo, cliente):
    _pergunta_respondida(cliente)
    Message.objects.update(created_at=timezone.now() - timedelta(hours=9))

    _pergunta_respondida(cliente, ident="M2")

    assert Conversation.objects.count() == 2


def test_nova_conversa_e_fonte(paulo, cliente):
    _pergunta_respondida(cliente)

    assert _receber(_evento("fonte", ident="M2"), cliente)[0] == "fonte"
    assert "```" in cliente.enviados[-1]["texto"] and "vendas_consolidado" in cliente.enviados[-1]["texto"]
    assert _receber(_evento("Nova conversa!", ident="M3"), cliente)[0] == "nova_conversa"
    assert Conversation.objects.count() == 2


def test_parar_interrompe_a_pergunta_em_andamento(paulo, cliente):
    conversa = Conversation.objects.create(user=paulo, canal="whatsapp", whatsapp_jid=f"{PAULO}@s.whatsapp.net")
    pendente = Message.objects.create(conversation=conversa, direction="in", content="vendas",
                                      client_message_id="M0", status=Message.Status.PROCESSING)

    assert servicos.parar_se_pedido(_evento("Parar", ident="M9"), cliente=cliente)

    pendente.refresh_from_db()
    assert pendente.status == Message.Status.CANCELLED
    assert cliente.enviados[-1]["texto"] == servicos.TEXTO_PAROU


# ------------------------------------------------------------ 👍/👎 e o aviso


def test_reacao_vira_avaliacao_e_sem_reacao_desfaz(paulo, cliente):
    _pergunta_respondida(cliente)
    alvo = cliente.enviados[-1]["id"]

    reacao = {"reactionMessage": {"text": "👎", "key": {"id": alvo}}}
    assert _receber(_evento(message=reacao, ident="R1"), cliente)[0] == "avaliacao"
    assert Avaliacao.objects.get().nota == "down"

    reacao["reactionMessage"]["text"] = ""
    _receber(_evento(message=reacao, ident="R2"), cliente)
    assert not Avaliacao.objects.exists()


def test_no_whatsapp_a_resposta_vem_direto_sem_o_entendi(paulo, cliente, monkeypatch):
    """2026-09-24: o "Entendi: … Já volto com os números" saiu do WhatsApp a
    pedido do Rubens. Só a resposta é enviada; o "digitando…" continua."""
    monkeypatch.setattr(aviso, "cliente_configurado", lambda: cliente)

    _pergunta_respondida(cliente)

    textos = [e["texto"] for e in cliente.enviados if e["tipo"] == "texto"]
    assert textos == ["Foram 777 unidades em ago/2026."]


def test_aviso_nao_sai_para_pergunta_do_chat_web(cliente, monkeypatch):
    monkeypatch.setattr(aviso, "cliente_configurado", lambda: cliente)

    progresso.definir(999, "Montando a consulta", etapa="entendi", entendimento="qualquer coisa")

    assert cliente.enviados == []


# ------------------------------------------------------------ webhook


def test_webhook_confere_o_segredo_e_a_origem(monkeypatch):
    monkeypatch.setenv("WHATSAPP_WEBHOOK_TOKEN", "segredo")
    enfileirados = []
    monkeypatch.setattr("whatsapp.views.tasks.receber.apply_async",
                        lambda args, countdown: enfileirados.append((args, countdown)))
    http = APIClient()

    assert http.post("/api/whatsapp/webhook/errado/", {}, format="json").status_code == 404
    assert http.post("/api/whatsapp/webhook/segredo/", _evento("oi"), format="json",
                     HTTP_X_FORWARDED_FOR="1.2.3.4").status_code == 404
    assert http.post("/api/whatsapp/webhook/segredo/", _evento("oi"), format="json").status_code == 200
    assert len(enfileirados) == 1
    # Espera sorteada antes de atender, contra o padrão de robô (2026-09-24).
    assert 3 <= enfileirados[0][1] <= 30


def test_webhook_sem_segredo_configurado_recusa_tudo():
    assert APIClient().post("/api/whatsapp/webhook/qualquer/", {}, format="json").status_code == 404


def test_planilha_mandada_no_whatsapp_segue_o_caminho_do_anexo(paulo, cliente):
    """O mesmo caminho do botão de anexar (ADR-0024): validada, resumida e só
    a forma sobe ao modelo."""
    import io

    from openpyxl import Workbook

    livro = Workbook()
    livro.active.append(["Rede", "Unidades"])
    livro.active.append(["Pague Menos", None])
    arquivo = io.BytesIO()
    livro.save(arquivo)
    cliente.midias["D1"] = arquivo.getvalue()
    documento = {"documentMessage": {"fileName": "redes.xlsx", "caption": "preencha as unidades de agosto"}}

    _, provider = _receber(_evento(message=documento, ident="D1"), cliente,
                           [plano(intent="clarify", sql="", clarification_question="De qual mês?")])

    pedido = provider.plan_requests[0]
    assert pedido.question == "preencha as unidades de agosto"
    assert "Rede" in pedido.planilha
    assert Message.objects.get(direction="in").anexo_tipo == "planilha"


def test_arquivo_recusado_vira_aviso_sem_chamar_a_ia(paulo, cliente):
    cliente.midias["D2"] = b"isto nao e imagem"

    resultado, provider = _receber(_evento(message={"imageMessage": {"caption": "o que diz?"}}, ident="D2"), cliente)

    assert resultado == "anexo_recusado" and provider.plan_requests == []


def test_mencao_nao_reconhecida_fica_para_a_pagina_de_conexao(grupo, cliente):
    """Nos grupos que escondem o número, a menção ao Jarvis chega como @lid.
    Até ele ser configurado, a marcação não chama — e fica registrada para
    quem faz o setup achar o identificador."""
    _receber(_no_grupo("@998877 vendas", mencao=False, mentionedJid=["998877@lid"]), cliente)

    assert cache.get(servicos.CHAVE_DAS_MENCOES)[0]["mencionados"] == ["998877@lid"]


def test_com_o_lid_configurado_a_mesma_mencao_chama(grupo, cliente, monkeypatch):
    monkeypatch.setenv("WHATSAPP_LID_JARVIS", "998877@lid")

    resultado, provider = _receber(_no_grupo("@998877 vendas por mês", mencao=False, mentionedJid=["998877@lid"]),
                                   cliente, [plano()], [resposta("Foram 777 unidades em ago/2026.")])

    assert resultado == "respondida"
    assert provider.plan_requests[0].question == "vendas por mês"


def test_contato_cadastrado_com_o_nono_digito_fala_mesmo_se_o_whatsapp_manda_sem(paulo, cliente):
    """2026-09-24: o WhatsApp identificou o próprio Jarvis como 553190054127,
    sem o 9. O Paulo está cadastrado com o 9 (5511977776666); a mensagem dele
    chegando como 551177776666 não pode ser ignorada."""
    resultado, _ = _receber(_evento("vendas por mês", jid="551177776666@s.whatsapp.net"), cliente,
                            [plano(entendimento="Unidades por mês")], [resposta("Foram 777 unidades em ago/2026.")])

    assert resultado == "respondida"


def test_atraso_da_resposta_respeita_os_limites(monkeypatch):
    from whatsapp import config

    sorteios = [config.atraso_da_resposta() for _ in range(200)]
    assert min(sorteios) >= 3 and max(sorteios) <= 30
    assert len({round(s, 3) for s in sorteios}) > 50      # sorteado, não fixo

    monkeypatch.setenv("WHATSAPP_ATRASO_MIN_S", "0")
    monkeypatch.setenv("WHATSAPP_ATRASO_MAX_S", "0")
    assert config.atraso_da_resposta() == 0


def test_contato_sem_usuario_ganha_um_usuario_tecnico_e_fala(cliente):
    """2026-09-24: liberar pelo número, sem a pessoa ter entrado no chat web."""
    contato = ContatoWhatsApp.objects.create(numero="5531988887777", nome="Ana Souza")

    assert contato.user.username == "whatsapp-5531988887777"
    assert (contato.user.first_name, contato.user.last_name) == ("Ana", "Souza")
    assert not contato.user.has_usable_password() and not contato.user.email

    resultado, _ = _receber(_evento("vendas por mês", jid="553188887777@s.whatsapp.net"), cliente,
                            [plano(entendimento="Unidades por mês")], [resposta("Foram 777 unidades em ago/2026.")])
    assert resultado == "respondida"
    assert Conversation.objects.get().user == contato.user


def test_admin_cadastra_contato_so_com_o_numero(admin_client):
    resposta_http = admin_client.post("/admin/whatsapp/contatowhatsapp/add/", {
        "numero": "+55 (31) 98888-7777", "nome": "Ana Souza", "user": "", "ativo": "on", "observacao": "",
    })

    assert resposta_http.status_code == 302, resposta_http.content.decode()[:500]
    assert ContatoWhatsApp.objects.get().user.username == "whatsapp-5531988887777"


# ------------------------------------------------------------ @lid aprendido


def _marcado_por_lid(texto, lid, ident="L1"):
    return _evento(jid=GRUPO, ident=ident, participant=f"{PAULO}@s.whatsapp.net",
                   message={"extendedTextMessage": {"text": texto, "contextInfo": {"mentionedJid": [f"{lid}@lid"]}}})


def test_jarvis_marcado_por_lid_aprende_o_proprio_lid_e_responde(grupo, cliente):
    """2026-09-24, primeiro grupo de teste: "@22777050443952 , quem é você?"
    chegou só com o @lid e o Jarvis ficou calado. A lista de participantes
    liga o @lid ao número do Jarvis: ele aprende e responde."""
    cliente.membros[GRUPO] = [
        {"id": "22777050443952@lid", "numero": JARVIS},
        {"id": "99999999999999@lid", "numero": PAULO},
    ]

    resultado, _ = _receber(_marcado_por_lid("@22777050443952 , quem é você?", "22777050443952"), cliente,
                            [plano(entendimento="Apresentação")], [resposta("Sou o Jarvis, o assistente de dados.")])

    assert resultado == "respondida"
    assert config.lid_do_jarvis() == "22777050443952@lid"
    pergunta = Message.objects.get(direction="in")
    assert "22777050443952" not in pergunta.content          # a marcação sai da pergunta

    # A segunda marcação já não consulta os participantes.
    cliente.membros.clear()
    resultado, _ = _receber(_marcado_por_lid("@22777050443952 e em julho?", "22777050443952", ident="L2"), cliente,
                            [plano(entendimento="Julho")], [resposta("Foram 761 unidades em jul/2026.")])
    assert resultado == "respondida"


def test_marcar_outra_pessoa_por_lid_nao_chama_o_jarvis(grupo, cliente):
    cliente.membros[GRUPO] = [
        {"id": "22777050443952@lid", "numero": JARVIS},
        {"id": "99999999999999@lid", "numero": PAULO},
    ]

    resultado, _ = _receber(_marcado_por_lid("@99999999999999 viu isso?", "99999999999999"), cliente)

    assert resultado == "grupo_sem_mencao"
    assert config.lid_do_jarvis() == "22777050443952@lid"   # aprendeu mesmo assim
