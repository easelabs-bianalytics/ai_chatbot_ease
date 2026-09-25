"""Áudio no WhatsApp (ADR-0029, 2026-09-25).

Antes o Jarvis respondia "Ainda não ouço áudio". Agora transcreve:

- no privado, todo áudio de contato liberado;
- no grupo, o áudio que cita uma mensagem do Jarvis, ou o que diz "Jarvis";
  os demais são descartados sem gravar nada.

A resposta vem direto. Até 2026-09-25 ela começava com "🎙️ Ouvi: …"; era
para os testes e saiu. A transcrição fica gravada como a pergunta.
"""

import pytest

from messaging.models import Message
from whatsapp import audio, saida, servicos
from whatsapp.audio import TranscritorFake
from tests.fakes.providers import ScriptedAIProvider, plano, resposta
from tests.integration.test_whatsapp import (  # noqa: F401
    GRUPO,
    JARVIS,
    MESES,
    PAULO,
    _evento,
    cliente,
    grupo,
    numero_do_jarvis,
    paulo,
)
from datasource.executors.fake import FakeQueryExecutor

pytestmark = pytest.mark.django_db

OGG = b"OggS-audio-de-teste"


def _audio(ident="A1", segundos=6, jid=f"{PAULO}@s.whatsapp.net", contexto=None, **chave):
    corpo = {"seconds": segundos, "mimetype": "audio/ogg; codecs=opus"}
    if contexto:
        corpo["contextInfo"] = contexto
    return _evento(jid=jid, ident=ident, message={"audioMessage": corpo}, **chave)


def _no_grupo(ident="GA1", **kw):
    return _audio(ident=ident, jid=GRUPO, participant=f"{PAULO}@s.whatsapp.net", **kw)


def _receber(payload, cliente, transcritor, planos=(), respostas=()):
    provider = ScriptedAIProvider(list(planos), list(respostas))
    resultado = servicos.receber(payload, cliente=cliente, provider=provider,
                                 executor=FakeQueryExecutor([MESES]), transcritor=transcritor)
    return resultado, provider


def test_audio_no_privado_vira_pergunta_e_a_resposta_vem_direto(paulo, cliente):
    cliente.midias["A1"] = OGG
    transcritor = TranscritorFake(["quantas unidades vendemos em agosto?"])

    resultado, provider = _receber(_audio(), cliente, transcritor, [plano()],
                                   [resposta("Foram 777 unidades em ago/2026.")])

    assert resultado == "respondida"
    assert transcritor.recebidos == [(OGG, "audio/ogg; codecs=opus")]
    assert provider.plan_requests[0].question == "quantas unidades vendemos em agosto?"
    # A pergunta gravada é a transcrição: é o que aparece no chat web.
    assert Message.objects.get(direction="in").content == "quantas unidades vendemos em agosto?"
    assert [e["texto"] for e in cliente.enviados if e["tipo"] == "texto"] == ["Foram 777 unidades em ago/2026."]


def test_audio_longo_demais_nao_e_transcrito(paulo, cliente):
    transcritor = TranscritorFake(["não devia chegar aqui"])

    resultado, _ = _receber(_audio(segundos=audio.MAX_SEGUNDOS + 1), cliente, transcritor)

    assert resultado == "audio_longo"
    assert transcritor.recebidos == []
    assert "3 minutos" in cliente.enviados[-1]["texto"]


def test_audio_que_nao_vira_texto_pede_para_repetir(paulo, cliente):
    cliente.midias["A1"] = OGG

    resultado, _ = _receber(_audio(), cliente, TranscritorFake(falhar=True))

    assert resultado == "audio_nao_entendido"
    assert "Não consegui entender o áudio" in cliente.enviados[-1]["texto"]
    assert not Message.objects.exists()


def test_no_grupo_o_audio_que_diz_jarvis_e_respondido(grupo, cliente):
    cliente.midias["GA1"] = OGG

    resultado, _ = _receber(_no_grupo(), cliente, TranscritorFake(["Jarvis, quanto vendemos em agosto?"]),
                            [plano()], [resposta("Foram 777 unidades em ago/2026.")])

    assert resultado == "respondida"


def test_no_grupo_o_audio_sem_jarvis_e_descartado_sem_rastro(grupo, cliente):
    """Conversa entre as pessoas: transcrita só para procurar o nome, e nada
    fica gravado nem é respondido."""
    cliente.midias["GA1"] = OGG

    resultado, provider = _receber(_no_grupo(), cliente, TranscritorFake(["pessoal, a reunião é às três"]))

    assert resultado == "audio_sem_jarvis"
    assert provider.plan_requests == []
    assert not Message.objects.exists()
    assert cliente.enviados == []


def test_no_grupo_o_audio_que_responde_ao_jarvis_e_atendido_sem_dizer_o_nome(grupo, cliente):
    servicos.receber(_evento(jid=GRUPO, ident="G1", participant=f"{PAULO}@s.whatsapp.net", message={
        "extendedTextMessage": {"text": f"@{JARVIS} vendas por mês",
                                "contextInfo": {"mentionedJid": [f"{JARVIS}@s.whatsapp.net"]}}}),
        cliente=cliente, provider=ScriptedAIProvider([plano()], [resposta("Foram 777 unidades em ago/2026.")]),
        executor=FakeQueryExecutor([MESES]))
    id_do_jarvis = cliente.enviados[-1]["id"]
    cliente.midias["GA2"] = OGG

    resultado, _ = _receber(_no_grupo(ident="GA2", contexto={"stanzaId": id_do_jarvis}), cliente,
                            TranscritorFake(["e em julho?"]), [plano()], [resposta("Foram 761 unidades em jul/2026.")])

    assert resultado == "respondida"


def test_no_grupo_o_arquivo_logo_depois_de_chamar_o_jarvis_conta_como_chamada(grupo, cliente):
    """"Jarvis, preenche a planilha que vou mandar" e, em seguida, o arquivo,
    sem marcação: é a continuação do pedido."""
    cliente.midias["GA1"] = OGG
    _receber(_no_grupo(), cliente, TranscritorFake(["Jarvis, vou mandar uma planilha, preenche com o sell out"]),
             [plano("", intent="conversation", user_message="Pode mandar.")])
    arquivo = servicos.entrada.ler(_evento(jid=GRUPO, ident="GD1", participant=f"{PAULO}@s.whatsapp.net",
                                           message={"documentMessage": {"fileName": "redes.xlsx"}}))
    de_outra_pessoa = servicos.entrada.ler(_evento(jid=GRUPO, ident="GD2", participant="5511911112222@s.whatsapp.net",
                                                   message={"documentMessage": {"fileName": "redes.xlsx"}}))

    assert servicos._chamou_o_jarvis(arquivo, cliente)
    assert not servicos._chamou_o_jarvis(de_outra_pessoa, cliente)


@pytest.mark.parametrize("texto,esperado", [
    ("Jarvis, quanto vendemos?", True),
    ("JÁRVIS me diz o sell out", True),
    ("djarvis qual o share", True),
    # 2026-09-25: o áudio "Jarvis, eu vou te enviar uma planilha" voltou assim
    ("Javis, eu vou te enviar uma planilha em Excel e eu quero que você preencha ela", True),
    ("Jarbis, quanto vendemos em agosto?", True),
    ("Jervis me manda o PX", True),
    ("Chárvis, e o estoque da Raia?", True),
    ("jar vis, qual o share?", True),
    ("pessoal, bom dia", False),
    ("o jarvisson chegou", False),
    ("vou mandar a planilha de vendas por email", False),
    ("o Davis e o Travis foram na reunião", False),
])
def test_nome_do_jarvis_no_audio(texto, esperado):
    assert audio.chamou_o_jarvis(texto) is esperado
