"""Várias mensagens ao mesmo tempo (2026-09-30).

Com o worker atendendo quatro perguntas em paralelo, o que não pode
acontecer:

- duas perguntas da MESMA conversa em paralelo: a segunda leria a primeira
  ainda sem resposta no histórico, e a resposta sairia misturada;
- a espera sorteada do WhatsApp inverter a ordem de duas perguntas seguidas;
- no grupo, o "e em julho?" do Bruno virar seguimento da pergunta da Ana;
- o "parar" de uma pessoa cancelar a pergunta de outra;
- no privado, duas respostas seguidas sem dizer a qual pergunta cada uma é.
"""

import pytest
from celery.exceptions import Retry

from ai_orchestrator import orchestrator
from ai_orchestrator.tasks import process_message
from conversations.models import Conversation
from messaging import fila
from messaging.models import Message
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from tests.integration.test_whatsapp import (  # noqa: F401
    GRUPO,
    JARVIS,
    PAULO,
    _evento,
    _no_grupo,
    _receber,
    cliente,
    grupo,
    numero_do_jarvis,
    paulo,
)
from whatsapp import servicos, tasks

pytestmark = pytest.mark.django_db

BRUNO = "5511955554444"


# ------------------------------------------------------------ a fila


def test_senhas_na_ordem_de_chegada_e_uma_de_cada_vez():
    primeira, segunda = fila.tirar_senha("c1"), fila.tirar_senha("c1")

    assert (primeira, segunda) == (1, 2)
    assert fila.e_a_vez("c1", 1) and not fila.e_a_vez("c1", 2)
    fila.passar_a_vez("c1", 1)
    assert fila.e_a_vez("c1", 2)


def test_conversas_diferentes_nao_esperam_uma_pela_outra():
    fila.tirar_senha("c1")
    fila.tirar_senha("c1")

    assert fila.e_a_vez("c2", fila.tirar_senha("c2"))


def test_senha_perdida_nao_trava_a_conversa(monkeypatch):
    """O worker caiu no meio da primeira: a segunda não espera para sempre."""
    fila.tirar_senha("c1")
    segunda = fila.tirar_senha("c1")
    agora = fila.time.time()
    monkeypatch.setattr(fila.time, "time", lambda: agora + fila.ESPERA_MAXIMA_S + 1)

    assert fila.e_a_vez("c1", segunda)


def test_whatsapp_fora_da_vez_espera_e_depois_responde_na_ordem(paulo, cliente):
    """A espera sorteada pode fazer a segunda pergunta ficar pronta antes da
    primeira: ela espera a vez, e as duas saem na ordem em que chegaram."""
    conversa = f"whatsapp:{PAULO}@s.whatsapp.net"
    s1, s2 = fila.tirar_senha(conversa), fila.tirar_senha(conversa)
    provider = ScriptedAIProvider([plano(), plano()], [resposta("Foram 777 unidades em ago/2026."),
                                                        resposta("Foram 761 unidades em jul/2026.")])
    servicos_receber = servicos.receber

    def receber_com_fakes(payload, **kw):
        return servicos_receber(payload, cliente=cliente, provider=provider, **kw)

    from datasource.executors.fake import FakeQueryExecutor
    from tests.integration.test_whatsapp import MESES

    def receber_com_executor(payload, **kw):
        return servicos_receber(payload, cliente=cliente, provider=provider,
                                executor=FakeQueryExecutor([MESES]), **kw)

    tasks.servicos.receber = receber_com_executor
    try:
        with pytest.raises(Retry):
            tasks.receber(_evento("e em julho?", ident="M2"), conversa=conversa, senha=s2)
        assert tasks.receber(_evento("vendas de agosto", ident="M1"), conversa=conversa, senha=s1) == "respondida"
        assert tasks.receber(_evento("e em julho?", ident="M2"), conversa=conversa, senha=s2) == "respondida"
    finally:
        tasks.servicos.receber = servicos_receber

    perguntas = list(Message.objects.filter(direction="in").order_by("id").values_list("content", flat=True))
    assert perguntas == ["vendas de agosto", "e em julho?"]


def test_chat_web_espera_a_pergunta_anterior_da_mesma_conversa(django_user_model):
    user = django_user_model.objects.create_user("ana", password="x")
    conversa = Conversation.objects.create(user=user)
    outra = Conversation.objects.create(user=user)
    Message.objects.create(conversation=conversa, direction="in", content="vendas de agosto",
                           client_message_id="w1", status=Message.Status.PROCESSING)
    segunda = Message.objects.create(conversation=conversa, direction="in", content="e em julho?",
                                     client_message_id="w2", status=Message.Status.RECEIVED)
    de_outra_conversa = Message.objects.create(conversation=outra, direction="in",
                                               content="o que você sabe responder?", client_message_id="w3",
                                               status=Message.Status.RECEIVED)

    with pytest.raises(Retry):
        process_message(segunda.pk, "fake")
    # outra conversa não espera
    assert process_message(de_outra_conversa.pk, "fake")


# ------------------------------------------------------------ o grupo


def _pergunta_no_grupo(texto, ident, numero, nome):
    return _evento(jid=GRUPO, ident=ident, participant=f"{numero}@s.whatsapp.net", pushName=nome, message={
        "extendedTextMessage": {"text": f"@{JARVIS} {texto}",
                                "contextInfo": {"mentionedJid": [f"{JARVIS}@s.whatsapp.net"]}}})


def test_no_grupo_o_planejador_sabe_quem_perguntou_cada_coisa(grupo, cliente):
    """A Ana pergunta das vendas; o Bruno manda "e em julho?". O planejador
    vê o nome de cada um no histórico e na pergunta."""
    evento_ana = _pergunta_no_grupo("vendas de agosto", "G1", PAULO, "Ana Souza")
    evento_ana["data"]["pushName"] = "Ana Souza"
    _receber(evento_ana, cliente, [plano()], [resposta("Foram 777 unidades em ago/2026.")])
    evento_bruno = _pergunta_no_grupo("e em julho?", "G2", BRUNO, "Bruno Lima")
    evento_bruno["data"]["pushName"] = "Bruno Lima"

    _, provider = _receber(evento_bruno, cliente, [plano()], [resposta("Foram 761 unidades em jul/2026.")])

    pedido = provider.plan_requests[0]
    assert pedido.question == "[Bruno Lima] e em julho?"
    perguntas = [h.text for h in pedido.history if h.direction == "in"]
    assert perguntas == ["[Ana Souza] vendas de agosto"]
    # no banco, a pergunta continua como a pessoa escreveu
    assert Message.objects.filter(content="e em julho?").exists()


def test_no_privado_a_pergunta_vai_sem_nome(paulo, cliente):
    _, provider = _receber(_evento("vendas de agosto"), cliente, [plano()], [resposta("Foram 777 unidades em ago/2026.")])

    assert provider.plan_requests[0].question == "vendas de agosto"


def test_parar_no_grupo_cancela_so_a_pergunta_de_quem_pediu(grupo, cliente):
    conversa = Conversation.objects.create(user=grupo.usuario, canal="whatsapp", whatsapp_jid=GRUPO)
    da_ana = Message.objects.create(conversation=conversa, direction="in", content="vendas", client_message_id="G1",
                                    status=Message.Status.PROCESSING, autor_externo=PAULO)
    do_bruno = Message.objects.create(conversation=conversa, direction="in", content="visitas",
                                      client_message_id="G2", status=Message.Status.RECEIVED, autor_externo=BRUNO)

    parar = _evento(jid=GRUPO, ident="G3", participant=f"{BRUNO}@s.whatsapp.net", message={
        "extendedTextMessage": {"text": f"@{JARVIS} parar", "contextInfo": {"mentionedJid": [f"{JARVIS}@s.whatsapp.net"]}}})
    assert servicos.parar_se_pedido(parar, cliente=cliente)

    da_ana.refresh_from_db()
    do_bruno.refresh_from_db()
    assert da_ana.status == Message.Status.PROCESSING
    assert do_bruno.status == Message.Status.CANCELLED


# ------------------------------------------------------------ o privado


def test_no_privado_a_resposta_cita_a_pergunta_quando_ja_chegou_outra(paulo, cliente):
    """Duas perguntas seguidas: a primeira resposta cita a pergunta, para a
    pessoa saber a qual das duas ela é."""
    conversa = f"whatsapp:{PAULO}@s.whatsapp.net"
    s1 = fila.tirar_senha(conversa)
    fila.tirar_senha(conversa)                     # a segunda já chegou

    from datasource.executors.fake import FakeQueryExecutor
    from tests.integration.test_whatsapp import MESES
    servicos.receber(_evento("vendas de agosto", ident="M1"), cliente=cliente,
                     provider=ScriptedAIProvider([plano()], [resposta("Foram 777 unidades em ago/2026.")]),
                     executor=FakeQueryExecutor([MESES]), conversa_na_fila=conversa, senha=s1)

    assert cliente.enviados[-1]["citar"] == "M1"


def test_no_privado_sozinha_a_resposta_nao_cita(paulo, cliente):
    conversa = f"whatsapp:{PAULO}@s.whatsapp.net"
    s1 = fila.tirar_senha(conversa)

    from datasource.executors.fake import FakeQueryExecutor
    from tests.integration.test_whatsapp import MESES
    servicos.receber(_evento("vendas de agosto", ident="M1"), cliente=cliente,
                     provider=ScriptedAIProvider([plano()], [resposta("Foram 777 unidades em ago/2026.")]),
                     executor=FakeQueryExecutor([MESES]), conversa_na_fila=conversa, senha=s1)

    assert cliente.enviados[-1]["citar"] == ""
