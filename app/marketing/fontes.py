"""Clientes das duas APIs do Marketing, só leitura (ADR-0032).

Cada um tem um dublê (`AreaMedicaFake`, `EmailMktFake`) com a mesma
interface: os testes nunca acessam rede. O token chega por variável de
ambiente (Secrets Manager em produção) e nunca vai para log.
"""

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

TEMPO_LIMITE = (10, 60)
MAX_TENTATIVAS = 5
# Respostas que passam: limite de taxa, servidor ocupado e os códigos do
# Cloudflare na frente da API. O ActiveCampaign devolveu 511 no meio da carga
# de 2026-10-01 — e 200 para a mesma chamada logo depois.
PASSAGEIROS = frozenset({408, 429, 500, 502, 503, 504, 511, 520, 521, 522, 523, 524})


class FonteIndisponivel(Exception):
    """A API não respondeu como devia. A carga daquela fonte para, e a
    anterior continua valendo (nada é apagado antes de tudo chegar)."""


class _Cliente:
    # Pausa entre chamadas, para ficar abaixo do limite de cada API.
    PAUSA = 0.0

    def __init__(self, url: str, sessao=None):
        self.url = url.rstrip("/")
        self.sessao = sessao or requests.Session()

    def _get(self, caminho: str, **params):
        espera = 2.0
        for tentativa in range(1, MAX_TENTATIVAS + 1):
            try:
                resposta = self.sessao.get(f"{self.url}{caminho}", params=params, timeout=TEMPO_LIMITE)
            except requests.RequestException as exc:
                motivo = f"sem resposta ({type(exc).__name__})"
            else:
                if resposta.status_code == 200:
                    if self.PAUSA:
                        time.sleep(self.PAUSA)
                    return resposta.json()
                if resposta.status_code in (401, 403):
                    raise FonteIndisponivel(f"{caminho}: acesso negado ({resposta.status_code}); confira o token")
                motivo = f"HTTP {resposta.status_code}"
                if resposta.status_code not in PASSAGEIROS:
                    raise FonteIndisponivel(f"{caminho}: {motivo}")
            if tentativa == MAX_TENTATIVAS:
                raise FonteIndisponivel(f"{caminho}: {motivo} depois de {MAX_TENTATIVAS} tentativas")
            logger.info("%s: %s; tentando de novo em %.0f s", caminho, motivo, espera)
            time.sleep(espera)
            espera *= 2
        raise FonteIndisponivel(caminho)  # inalcançável


class AreaMedica(_Cliente):
    """`GET {URL}/api/usuarios`, paginado (até 200 por página), Bearer token.
    3.849 cadastros em 2026-10-01: 20 chamadas, menos de 2 segundos."""

    POR_PAGINA = 200
    # 60 requisições por minuto por IP: uma por segundo fica abaixo.
    PAUSA = 1.0

    def __init__(self, url: str, token: str, sessao=None):
        super().__init__(url, sessao)
        self.sessao.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})

    @classmethod
    def do_ambiente(cls):
        return cls(os.environ["AREA_MEDICA_API_URL"], os.environ["AREA_MEDICA_API_TOKEN"])

    def usuarios(self) -> list:
        primeira = self._get("/api/usuarios", page=1, per_page=self.POR_PAGINA)
        usuarios = list(primeira.get("data") or [])
        for pagina in range(2, int(primeira.get("last_page") or 1) + 1):
            usuarios.extend(self._get("/api/usuarios", page=pagina, per_page=self.POR_PAGINA).get("data") or [])
        total = primeira.get("total")
        if total is not None and len(usuarios) < int(total):
            # A lista mudou no meio da paginação (cadastro novo empurra todo
            # mundo uma posição). Faltar gente é pior que demorar: refaz.
            raise FonteIndisponivel(f"/api/usuarios: vieram {len(usuarios)} de {total}")
        return usuarios


class EmailMkt(_Cliente):
    """API v3 do ActiveCampaign, header `Api-Token`. 17.954 contatos em
    2026-10-01, com campos, tags e listas vindo junto (`include`)."""

    POR_PAGINA = 100
    # O limite do ActiveCampaign é de 5 requisições por segundo.
    PAUSA = 0.25

    def __init__(self, url: str, token: str, sessao=None):
        super().__init__(url, sessao)
        self.sessao.headers.update({"Api-Token": token, "Accept": "application/json"})

    @classmethod
    def do_ambiente(cls):
        return cls(os.environ["EMAIL_MKT_API_URL"], os.environ["EMAIL_MKT_API_TOKEN"])

    def _todas(self, recurso: str, chave: str, **params) -> list:
        itens, offset = [], 0
        while True:
            pagina = self._get(f"/api/3/{recurso}", limit=self.POR_PAGINA, offset=offset, **params)
            lote = pagina.get(chave) or []
            itens.extend(lote)
            total = int((pagina.get("meta") or {}).get("total") or 0)
            offset += self.POR_PAGINA
            if not lote or offset >= total:
                return itens

    def campos(self) -> list:
        return self._todas("fields", "fields")

    def listas(self) -> list:
        return self._todas("lists", "lists")

    def tags(self) -> list:
        return self._todas("tags", "tags")

    def campanhas(self) -> list:
        return self._todas("campaigns", "campaigns")

    def contatos(self) -> dict:
        """{"contacts", "fieldValues", "contactTags", "contactLists"}, de
        todas as páginas, na ordem do id — a ordem estável é o que impede um
        contato de cair entre duas páginas."""
        juntos = {"contacts": [], "fieldValues": [], "contactTags": [], "contactLists": []}
        offset, total = 0, None
        while total is None or offset < total:
            pagina = self._get(
                "/api/3/contacts", limit=self.POR_PAGINA, offset=offset, **{"orders[id]": "ASC"},
                include="fieldValues,contactTags,contactLists",
            )
            total = int((pagina.get("meta") or {}).get("total") or 0)
            for chave in juntos:
                juntos[chave].extend(pagina.get(chave) or [])
            if not pagina.get("contacts"):
                break
            offset += self.POR_PAGINA
        return juntos


class AreaMedicaFake:
    def __init__(self, usuarios=(), erro: Exception | None = None):
        self._usuarios, self._erro = list(usuarios), erro

    def usuarios(self):
        if self._erro:
            raise self._erro
        return list(self._usuarios)


class EmailMktFake:
    def __init__(self, contatos=None, campos=(), listas=(), tags=(), campanhas=(), erro: Exception | None = None):
        self._contatos = contatos or {"contacts": [], "fieldValues": [], "contactTags": [], "contactLists": []}
        self._campos, self._listas, self._tags, self._campanhas = list(campos), list(listas), list(tags), list(campanhas)
        self._erro = erro

    def _ou_erro(self, valor):
        if self._erro:
            raise self._erro
        return valor

    def campos(self):
        return self._ou_erro(list(self._campos))

    def listas(self):
        return self._ou_erro(list(self._listas))

    def tags(self):
        return self._ou_erro(list(self._tags))

    def campanhas(self):
        return self._ou_erro(list(self._campanhas))

    def contatos(self):
        return self._ou_erro(dict(self._contatos))
