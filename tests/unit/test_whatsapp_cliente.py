"""Contrato HTTP com a Evolution API (ADR-0028), sem rede.

A sessão HTTP é trocada por uma que só guarda o pedido. O que se fixa é o
formato que a Evolution v2.3.7 aceita — confirmado na referência — e que
falha dela vira `WhatsAppIndisponivel`, nunca exceção crua.
"""

import base64

import pytest
import requests

from whatsapp.cliente import Citacao, EvolutionCliente, WhatsAppIndisponivel


class _Resposta:
    def __init__(self, corpo=None, status=200):
        self._corpo, self.status_code = corpo or {}, status
        self.content = b"x"

    def json(self):
        return self._corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class _Sessao:
    def __init__(self, *respostas):
        self.respostas, self.pedidos = list(respostas), []

    def post(self, url, headers, json, timeout):
        self.pedidos.append(("POST", url, headers, json))
        return self.respostas.pop(0) if self.respostas else _Resposta({"key": {"id": "OUT1"}})

    def get(self, url, headers, timeout):
        self.pedidos.append(("GET", url, headers, None))
        return self.respostas.pop(0) if self.respostas else _Resposta({})


def _cliente(*respostas):
    sessao = _Sessao(*respostas)
    return EvolutionCliente(base_url="http://127.0.0.1:8080/", api_key="chave", instancia="jarvis", sessao=sessao), sessao


def test_texto_citando_a_pergunta_do_grupo():
    cliente, sessao = _cliente()

    ident = cliente.enviar_texto("1203@g.us", "Foram 777.", citar=Citacao("G1", "1203@g.us", "vendas", "5511@s.whatsapp.net"))

    metodo, url, cabecalhos, corpo = sessao.pedidos[0]
    assert ident == "OUT1"
    assert url == "http://127.0.0.1:8080/message/sendText/jarvis"
    assert cabecalhos["apikey"] == "chave"
    assert corpo["quoted"]["key"] == {"id": "G1", "remoteJid": "1203@g.us", "fromMe": False,
                                      "participant": "5511@s.whatsapp.net"}


def test_arquivo_vai_em_base64():
    cliente, sessao = _cliente()

    cliente.enviar_arquivo("5511@s.whatsapp.net", b"\x89PNG", "grafico.png", "image/png", tipo="image", legenda="PX")

    corpo = sessao.pedidos[0][3]
    assert (corpo["mediatype"], corpo["fileName"], corpo["caption"]) == ("image", "grafico.png", "PX")
    assert base64.b64decode(corpo["media"]) == b"\x89PNG"


def test_falha_da_evolution_vira_indisponivel():
    cliente, _ = _cliente(_Resposta(status=500))

    with pytest.raises(WhatsAppIndisponivel):
        cliente.enviar_texto("5511@s.whatsapp.net", "oi")


def test_digitando_nunca_derruba_a_resposta():
    cliente, _ = _cliente(_Resposta(status=500))

    cliente.digitando("5511@s.whatsapp.net")      # não levanta


def test_configurar_liga_grupos_recusa_chamada_e_aponta_o_webhook():
    """groupsIgnore desligado de propósito: precisamos dos grupos, e a trava
    é o cadastro (ADR-0028) — não a configuração da Evolution."""
    cliente, sessao = _cliente(_Resposta(status=404))

    cliente.configurar("http://127.0.0.1:8000/api/whatsapp/webhook/segredo/")

    urls = [p[1].replace("http://127.0.0.1:8080", "") for p in sessao.pedidos]
    assert urls == ["/instance/fetchInstances?instanceName=jarvis", "/instance/create",
                    "/settings/set/jarvis", "/webhook/set/jarvis"]
    ajustes = sessao.pedidos[2][3]
    assert ajustes["groupsIgnore"] is False and ajustes["rejectCall"] is True and ajustes["readMessages"] is False
    assert sessao.pedidos[3][3]["webhook"]["events"] == ["MESSAGES_UPSERT"]


def test_lista_os_grupos_do_numero_para_o_cadastro():
    """Liberar um grupo exige o identificador dele (@g.us); a página de
    conexão lista os grupos de que o número participa."""
    cliente, sessao = _cliente(_Resposta([{"id": "2@g.us", "subject": "Vendas NE"}, {"id": "1@g.us", "subject": "BI"}]))

    assert cliente.grupos() == [{"jid": "1@g.us", "nome": "BI"}, {"jid": "2@g.us", "nome": "Vendas NE"}]
    assert sessao.pedidos[0][1].endswith("/group/fetchAllGroups/jarvis?getParticipants=false")


def test_instancia_que_nao_existe_nao_e_evolution_fora():
    """2026-09-24, primeira abertura em produção: o 404 da instância ainda
    não criada aparecia como "A Evolution não respondeu"."""
    cliente, _ = _cliente(_Resposta({"message": "not found"}, status=404))

    assert cliente.estado() == {"estado": "sem_instancia"}


def test_evolution_fora_continua_sendo_erro():
    cliente, _ = _cliente(_Resposta({}, status=500))

    with pytest.raises(WhatsAppIndisponivel):
        cliente.estado()


def test_participantes_ligam_o_lid_ao_numero():
    cliente, sessao = _cliente(_Resposta({"participants": [
        {"id": "22777050443952@lid", "phoneNumber": "553190054127@s.whatsapp.net", "admin": None},
    ]}))

    assert cliente.participantes("120363410540006151@g.us") == [{"id": "22777050443952@lid", "numero": "553190054127"}]
    # o @ do grupo vai codificado: sem isso a Evolution respondia 404
    assert sessao.pedidos[0][1].endswith("/group/participants/jarvis?groupJid=120363410540006151%40g.us")


def test_404_fora_das_rotas_da_instancia_nao_diz_que_ela_nao_existe():
    from whatsapp.cliente import InstanciaInexistente

    cliente, _ = _cliente(_Resposta({}, status=404))

    with pytest.raises(WhatsAppIndisponivel) as erro:
        cliente.participantes("1203@g.us")
    assert not isinstance(erro.value, InstanciaInexistente)
