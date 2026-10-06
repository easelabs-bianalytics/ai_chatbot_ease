"""Onde os arquivos da conversa ficam guardados (ADR-0034).

Em produção, um bucket S3 privado e criptografado (`JARVIS_ARQUIVOS_BUCKET`),
com regra de ciclo de vida que apaga cada arquivo aos dois anos. Sem o bucket:

- em desenvolvimento (`DEBUG`) e nos testes (`ARMAZEM_EM_MEMORIA`), um
  armazém em memória — os testes nunca falam com a AWS (ADR-0005);
- em produção, o armazém fica **desligado**: o arquivo não é fixado e a
  conversa segue só com o Redis, como antes. Memória em produção seria pior
  que nada — o registro ficaria no banco apontando para um arquivo que mora
  num processo só (o web, não o worker) e some no próximo deploy.

Só guarda, busca e apaga bytes por chave. Quem decide o que guardar e quem
pode buscar é o `deposito`.
"""

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)


class Armazem:
    def guardar(self, chave: str, dados: bytes) -> None:
        raise NotImplementedError

    def buscar(self, chave: str) -> bytes | None:
        raise NotImplementedError

    def apagar(self, chaves) -> None:
        raise NotImplementedError


class ArmazemEmMemoria(Armazem):
    def __init__(self):
        self.arquivos = {}

    def guardar(self, chave, dados):
        self.arquivos[chave] = bytes(dados)

    def buscar(self, chave):
        return self.arquivos.get(chave)

    def apagar(self, chaves):
        for chave in chaves:
            self.arquivos.pop(chave, None)


class ArmazemS3(Armazem):
    def __init__(self, bucket: str, regiao: str = "sa-east-1"):
        import boto3

        self.bucket = bucket
        self._s3 = boto3.client("s3", region_name=regiao)

    def guardar(self, chave, dados):
        self._s3.put_object(Bucket=self.bucket, Key=chave, Body=dados, ServerSideEncryption="AES256")

    def buscar(self, chave):
        from botocore.exceptions import ClientError

        try:
            return self._s3.get_object(Bucket=self.bucket, Key=chave)["Body"].read()
        except ClientError as exc:
            # Passou dos dois anos (o ciclo de vida apagou) ou a conversa foi
            # apagada: é o caminho honesto do "expirou", não um erro.
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                return None
            raise

    def apagar(self, chaves):
        chaves = list(chaves)
        for inicio in range(0, len(chaves), 1000):
            lote = [{"Key": c} for c in chaves[inicio:inicio + 1000]]
            if lote:
                self._s3.delete_objects(Bucket=self.bucket, Delete={"Objects": lote, "Quiet": True})


class ArmazemDesligado(Armazem):
    """Produção sem bucket: guardar falha (e `fixar` registra no log), buscar
    não acha nada. A conversa continua funcionando com o Redis."""

    def guardar(self, chave, dados):
        raise RuntimeError("JARVIS_ARQUIVOS_BUCKET não está configurado")

    def buscar(self, chave):
        return None

    def apagar(self, chaves):
        pass


@lru_cache(maxsize=1)
def armazem() -> Armazem:
    from django.conf import settings

    bucket = os.environ.get("JARVIS_ARQUIVOS_BUCKET", "").strip()
    if not bucket:
        if settings.DEBUG or getattr(settings, "ARMAZEM_EM_MEMORIA", False):
            return ArmazemEmMemoria()
        logger.warning("JARVIS_ARQUIVOS_BUCKET vazio: os arquivos da conversa ficam só no Redis")
        return ArmazemDesligado()
    return ArmazemS3(bucket, os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "sa-east-1")
