"""Do evento do WhatsApp à resposta entregue (ADR-0028).

O caminho, na ordem — cada etapa pode encerrar sem gastar nada:

1. ler o evento (`entrada.py`); eco do próprio Jarvis e status não são conversa;
2. **cadastro**: número ou grupo liberado no Admin; o resto é ignorado em
   silêncio (lição da referência: o número responde em todo grupo em que
   estiver);
3. **no grupo, só quando chamado**: marcado com @jarvis, ou respondendo a
   uma mensagem do Jarvis; conversa entre as pessoas nunca é processada;
4. reação 👍/👎 numa mensagem do Jarvis vira avaliação (ADR-0027);
5. comandos: "nova conversa", "fonte", "1"/"2"/"3" para as continuações;
6. anexo (imagem, planilha) pelo mesmo caminho do chat web;
7. a pergunta é gravada (idempotente pelo id do WhatsApp) e respondida pelo
   MESMO orquestrador do chat web — regras, cota, planejamento, ancoragem e
   auditoria são os mesmos;
8. a resposta é montada para o WhatsApp (`saida.py`) e enviada.

"parar" não passa por aqui: precisa agir enquanto o worker ainda está
ocupado com a resposta, então é tratado na própria requisição do webhook
(`parar_se_pedido`).
"""

import logging
import re
import unicodedata
from dataclasses import replace
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from ai_orchestrator.orchestrator import handle_message
from ai_orchestrator.provider_factory import get_configured_provider
from attachments.limites import AnexoRecusado
from attachments.receber import preparar_anexo
from conversations.models import Conversation
from datasource.executors.factory import get_configured_executor
from datasource.models import QueryRun
from messaging.channels.base import InboundMessage
from messaging.channels.whatsapp import WhatsAppChannel
from messaging.models import Avaliacao, Message
from messaging.services import ingest_inbound_message
from whatsapp import audio, config, entrada, saida
from whatsapp.cliente import Citacao, WhatsAppIndisponivel, cliente_configurado
from whatsapp.models import ContatoWhatsApp, EnvioWhatsApp, GrupoWhatsApp

logger = logging.getLogger(__name__)

# O WhatsApp é uma conversa sem fim. Depois disto parado, a próxima mensagem
# abre outra conversa: o histórico que vai ao modelo é o do assunto atual.
INATIVIDADE = timedelta(hours=8)
# Quanto tempo o aviso "Entendi" e o "digitando" sabem para onde mandar.
SEGUNDOS_DO_PENDENTE = 10 * 60

UTIL = {"👍", "👍🏻", "👍🏼", "👍🏽", "👍🏾", "👍🏿", "❤️", "🙏", "👏"}
ERRADA = {"👎", "👎🏻", "👎🏼", "👎🏽", "👎🏾", "👎🏿"}

TEXTO_AUDIO_LONGO = (
    "Esse áudio passa de 3 minutos, e eu só ouço até aí. Me manda a pergunta num áudio mais curto "
    "ou por escrito?"
)
TEXTO_AUDIO_NAO_ENTENDIDO = "Não consegui entender o áudio. Pode repetir ou mandar por escrito?"
TEXTO_NOVA_CONVERSA = "Pronto: comecei uma conversa nova. Pode perguntar."
TEXTO_MENSAGEM_LONGA = (
    "Sua mensagem passou de {limite} caracteres, o máximo que eu leio de uma vez. "
    "Pode mandar em partes menores, ou anexar o conteúdo como arquivo?"
)
TEXTO_SEM_FONTE = "A última resposta desta conversa não consultou o banco, então não há consulta para mostrar."
TEXTO_PAROU = "Parei. Quando quiser, é só perguntar de novo."
TEXTO_NADA_A_PARAR = "Não há nenhuma pergunta sendo respondida agora."
# Arquivo mandado sem legenda. Neutro de propósito: se a pessoa já disse o
# que fazer com ele ("vou te mandar a planilha, preenche com o sell out"),
# o planejador segue o pedido anterior da conversa; se não disse, descreve o
# arquivo e oferece preencher. Até 2026-09-24 era "Recebi este arquivo.", e
# o Jarvis perguntava qual aba preencher em vez de dizer o que viu.
TEXTO_ARQUIVO_SEM_PERGUNTA = "Segue o arquivo."

# Arquivo no grupo, sem marcação, logo depois de a mesma pessoa chamar o
# Jarvis ("Jarvis, preenche a planilha que vou mandar"): conta como chamada.
MINUTOS_DO_ARQUIVO_SEGUINTE = 5


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", (texto or "").lower())
    return " ".join("".join(c for c in sem_acento if unicodedata.category(c) != "Mn").split()).strip(" .!?")


_PARAR = {"parar", "pare", "para", "cancelar", "cancela", "stop"}
_NOVA = {"nova conversa", "novo assunto", "outra conversa", "recomecar", "/nova", "/novo"}
_FONTE = {"fonte", "sql", "consulta", "qual a fonte", "de onde veio", "como chegou nisso", "/fonte"}


# ------------------------------------------------------------ quem pode falar


def _dono(recebida):
    """(usuário dono da conversa, grupo) ou (None, motivo)."""
    if recebida.grupo:
        grupo = GrupoWhatsApp.objects.filter(jid=recebida.jid, ativo=True).select_related("usuario").first()
        if grupo is None:
            logger.info("WhatsApp: grupo não liberado %s (%s) — ignorado", recebida.jid, recebida.nome)
            return None, "grupo_nao_liberado"
        return grupo.usuario, grupo
    contato = (
        ContatoWhatsApp.objects.filter(numero__in=entrada.formas_do_numero(recebida.numero), ativo=True, user__is_active=True)
        .select_related("user").first()
        if recebida.numero else None
    )
    if contato is None:
        # Só o fim do número no log: é dado pessoal de quem não é usuário.
        logger.info("WhatsApp: número não liberado …%s — ignorado", recebida.numero[-4:] or "(escondido)")
        return None, "contato_nao_liberado"
    return contato.user, None


def _chamou_o_jarvis(recebida, cliente=None) -> bool:
    if entrada.marcou_o_jarvis(recebida, config.numero_do_jarvis(), config.lid_do_jarvis()):
        return True
    if _aprendeu_o_lid(recebida, cliente):
        return True
    if _arquivo_logo_depois_de_chamar(recebida):
        return True
    # Responder (citando) uma mensagem do Jarvis também é chamá-lo.
    return bool(recebida.citada_id) and EnvioWhatsApp.objects.filter(externo_id=recebida.citada_id).exists()


def _arquivo_logo_depois_de_chamar(recebida) -> bool:
    """Arquivo sem marcação, da mesma pessoa que acabou de chamar o Jarvis
    no grupo. Só as mensagens que chamaram o Jarvis ficam gravadas, então
    qualquer pergunta dela nos últimos minutos é uma chamada."""
    if not (recebida.grupo and recebida.numero and recebida.tipo in (entrada.IMAGEM, entrada.DOCUMENTO)):
        return False
    return Message.objects.filter(
        conversation__canal=Conversation.Canal.WHATSAPP, conversation__whatsapp_jid=recebida.jid,
        direction=Message.Direction.INBOUND, autor_externo__in=entrada.formas_do_numero(recebida.numero),
        created_at__gte=timezone.now() - timedelta(minutes=MINUTOS_DO_ARQUIVO_SEGUINTE),
    ).exists()


def _ouvir(recebida, cliente, transcritor):
    """Transcreve o áudio. Devolve (recebida como texto, "") ou (None, o que
    aconteceu).

    No grupo, o áudio que cita uma mensagem do Jarvis é atendido direto; os
    outros só seguem se o nome "Jarvis" aparece. O que não segue é
    descartado aqui: o texto não é gravado nem logado (ADR-0029)."""
    citou = recebida.grupo and _chamou_o_jarvis(recebida, cliente)
    responde = not recebida.grupo or citou
    citar = _citacao(recebida) if recebida.grupo else None
    if recebida.segundos > audio.MAX_SEGUNDOS:
        if responde:
            enviar_texto(cliente, recebida.jid, TEXTO_AUDIO_LONGO, citar=citar)
        return None, "audio_longo"
    try:
        dados = cliente.baixar_midia(recebida.bruto)
        texto = audio.transcrever_limpo(transcritor, dados, recebida.arquivo_mimetype)
    except (WhatsAppIndisponivel, audio.TranscricaoFalhou) as exc:
        logger.warning("WhatsApp: áudio de %ss não transcrito: %s", recebida.segundos, exc)
        if responde:
            enviar_texto(cliente, recebida.jid, TEXTO_AUDIO_NAO_ENTENDIDO, citar=citar)
        return None, "audio_nao_entendido"
    logger.info("WhatsApp: áudio de %ss transcrito (~US$ %.4f)", recebida.segundos, audio.custo(recebida.segundos))
    if not responde and not audio.chamou_o_jarvis(texto):
        return None, "audio_sem_jarvis"
    return replace(recebida, tipo=entrada.TEXTO, texto=texto), ""


def _aprendeu_o_lid(recebida, cliente=None) -> bool:
    """A marcação veio por @lid e o Jarvis ainda não conhece o dele.

    2026-09-24: no primeiro grupo de teste, "@Jarvis, quem é você?" chegou
    como 22777050443952@lid e o Jarvis ficou calado — só o número estava
    configurado. A lista de participantes do grupo liga cada @lid ao número;
    se o @lid marcado é o do número do Jarvis, ele o guarda e responde. Só
    consulta enquanto não conhece o próprio @lid."""
    lids = [j for j in recebida.mencionados if j.endswith("@lid")]
    numero = config.numero_do_jarvis()
    if not (recebida.grupo and lids and numero) or config.lid_do_jarvis():
        return False
    try:
        membros = (cliente or cliente_configurado()).participantes(recebida.jid)
    except WhatsAppIndisponivel:
        logger.warning("WhatsApp: não consegui ler os participantes de %s", recebida.jid, exc_info=True)
        return False
    formas = entrada.formas_do_numero(numero)
    for membro in membros:
        if membro["numero"] in formas and membro["id"].endswith("@lid"):
            config.aprender_lid(membro["id"])
            logger.info("WhatsApp: @lid do Jarvis aprendido: %s", membro["id"])
            return membro["id"] in lids
    return False


CHAVE_DAS_MENCOES = "whatsapp:mencoes_nao_reconhecidas"


def _guardar_mencao_nao_reconhecida(recebida) -> None:
    """Num grupo liberado, alguém marcou alguém que não é o Jarvis — ou é o
    Jarvis por um identificador (@lid) que ainda não está configurado. A
    página de conexão mostra as últimas: no teste do grupo, o @lid do Jarvis
    aparece ali para ir para WHATSAPP_LID_JARVIS."""
    ultimas = cache.get(CHAVE_DAS_MENCOES) or []
    ultimas = [{"grupo": recebida.jid, "texto": recebida.texto[:80], "mencionados": list(recebida.mencionados)},
               *ultimas][:10]
    cache.set(CHAVE_DAS_MENCOES, ultimas, timeout=7 * 24 * 3600)
    logger.info("WhatsApp: menção não reconhecida em %s: %s", recebida.jid, list(recebida.mencionados))


# ------------------------------------------------------------ conversa


def _conversa(dono, jid, nova: bool = False) -> Conversation:
    atual = (
        Conversation.objects.visiveis()
        .filter(user=dono, canal=Conversation.Canal.WHATSAPP, whatsapp_jid=jid)
        .order_by("-id").first()
    )
    if atual is not None and not nova:
        ultima = Message.objects.filter(conversation=atual).order_by("-id").values_list("created_at", flat=True).first()
        if ultima is None or timezone.now() - ultima < INATIVIDADE:
            return atual
    return Conversation.objects.create(user=dono, canal=Conversation.Canal.WHATSAPP, whatsapp_jid=jid)


def _ultima_resposta(conversa):
    return (
        Message.objects.filter(conversation=conversa, direction=Message.Direction.OUTBOUND)
        .select_related("in_reply_to__ai_reply").order_by("-id").first()
    )


def _escolha_de_sugestao(conversa, texto: str) -> str:
    """"2" logo depois de uma resposta com continuações numeradas."""
    if not re.fullmatch(r"[1-3]", texto.strip()):
        return ""
    anterior = _ultima_resposta(conversa)
    reply = getattr(getattr(anterior, "in_reply_to", None), "ai_reply", None)
    sugestoes = ((reply.raw_response or {}).get("sugestoes") or []) if reply is not None else []
    indice = int(texto.strip()) - 1
    return sugestoes[indice] if indice < len(sugestoes) else ""


def _texto_da_fonte(conversa) -> str:
    anterior = _ultima_resposta(conversa)
    reply = getattr(getattr(anterior, "in_reply_to", None), "ai_reply", None)
    consultas = list(reply.query_runs.filter(status=QueryRun.Status.SUCCESS).order_by("attempt")) if reply else []
    if not consultas:
        return TEXTO_SEM_FONTE
    partes = []
    for consulta in consultas[-3:]:
        base = f"Referência {consulta.reference_query_id}" if consulta.reference_query_id else "Consulta escrita pela IA"
        partes.append(f"*{base}* · {consulta.row_count or 0} linhas\n```\n{consulta.sql.strip()}\n```")
    return "\n\n".join(partes)


# ------------------------------------------------------------ envio


def _citacao(recebida) -> Citacao:
    chave = (recebida.bruto or {}).get("key") or {}
    return Citacao(id=recebida.id, jid=recebida.jid, texto=recebida.texto, participante=str(chave.get("participant") or ""))


def enviar_texto(cliente, jid, texto, message=None, citar=None, tipo=EnvioWhatsApp.Tipo.AVISO) -> str:
    externo = cliente.enviar_texto(jid, texto, citar=citar)
    EnvioWhatsApp.objects.create(message=message, externo_id=externo, jid=jid, tipo=tipo)
    return externo


def entregar(resposta, cliente, jid, citar=None, executor=None) -> int:
    """Manda a resposta (Message de saída) e registra cada envio. Falha da
    Evolution vira status FAILED na mensagem, nunca exceção: a resposta já
    está gravada e visível no chat web.

    A resposta a um áudio vem direto. Até 2026-09-25 ela começava com
    "🎙️ Ouvi: …"; era para os testes, e o Rubens pediu para tirar. A
    transcrição continua gravada como a pergunta, visível no chat web."""
    envios = saida.montar(resposta, executor=executor)
    enviados = 0
    try:
        for envio in envios:
            if envio.tipo == "texto":
                externo = cliente.enviar_texto(jid, envio.texto, citar=citar if enviados == 0 else None)
                tipo = EnvioWhatsApp.Tipo.TEXTO
            else:
                externo = cliente.enviar_arquivo(
                    jid, envio.dados, envio.nome, envio.mimetype,
                    tipo="image" if envio.tipo == "imagem" else "document", legenda=envio.texto,
                )
                tipo = EnvioWhatsApp.Tipo.IMAGEM if envio.tipo == "imagem" else EnvioWhatsApp.Tipo.DOCUMENTO
            EnvioWhatsApp.objects.create(message=resposta, externo_id=externo, jid=jid, tipo=tipo)
            enviados += 1
    except WhatsAppIndisponivel as exc:
        logger.warning("WhatsApp: resposta %s não saiu inteira (%s de %s)", resposta.pk, enviados, len(envios))
        Message.objects.filter(pk=resposta.pk).update(
            status=Message.Status.FAILED, delivery_detail=f"whatsapp: {enviados}/{len(envios)} enviados; {exc}"[:500],
        )
        return enviados
    Message.objects.filter(pk=resposta.pk).update(
        status=Message.Status.SENT, delivery_detail=f"whatsapp: {enviados} mensagem(ns)",
    )
    return enviados


# ------------------------------------------------------------ "parar"


def parar_se_pedido(payload, cliente=None) -> bool:
    """Trata "parar" na hora, na requisição do webhook. True se tratou."""
    recebida = entrada.ler(payload)
    if recebida is None or recebida.tipo != entrada.TEXTO:
        return False
    texto = recebida.texto
    if recebida.grupo:
        if not _chamou_o_jarvis(recebida, cliente):
            return False
        texto = entrada.sem_mencao(texto, config.numero_do_jarvis(), config.lid_do_jarvis())
    if _normalizar(texto) not in _PARAR:
        return False
    dono, grupo = _dono(recebida)
    if dono is None:
        return True       # não liberado: ignorado, e não segue para a fila
    cliente = cliente or cliente_configurado()
    paradas = Message.objects.filter(
        conversation__user=dono, conversation__whatsapp_jid=recebida.jid,
        direction=Message.Direction.INBOUND,
        status__in=(Message.Status.RECEIVED, Message.Status.PROCESSING),
    ).update(status=Message.Status.CANCELLED)
    try:
        enviar_texto(cliente, recebida.jid, TEXTO_PAROU if paradas else TEXTO_NADA_A_PARAR,
                     citar=_citacao(recebida) if recebida.grupo else None)
    except WhatsAppIndisponivel:
        logger.warning("WhatsApp: não consegui confirmar o \"parar\"", exc_info=True)
    return True


# ------------------------------------------------------------ o caminho todo


def receber(payload, cliente=None, provider=None, executor=None, transcritor=None) -> str:
    """Processa um evento. Devolve o que aconteceu (para o log e os testes)."""
    recebida = entrada.ler(payload)
    if recebida is None:
        return "ignorada"

    dono, grupo = _dono(recebida)
    if dono is None:
        return grupo  # o motivo

    if recebida.tipo == entrada.REACAO:
        return _reacao(recebida)
    ouvi = ""
    if recebida.tipo == entrada.AUDIO:
        cliente = cliente or cliente_configurado()
        recebida, motivo = _ouvir(recebida, cliente, transcritor or audio.transcritor_configurado())
        if recebida is None:
            return motivo
        ouvi = recebida.texto
    if recebida.grupo and not ouvi and not _chamou_o_jarvis(recebida, cliente):
        if recebida.mencionados:
            _guardar_mencao_nao_reconhecida(recebida)
        return "grupo_sem_mencao"

    cliente = cliente or cliente_configurado()
    citar = _citacao(recebida) if recebida.grupo else None
    texto = entrada.sem_mencao(recebida.texto, config.numero_do_jarvis(), config.lid_do_jarvis())
    if len(texto) > entrada.MAX_CARACTERES:
        # Como o chat web: recusa dizendo o porquê, em vez de cortar calado.
        enviar_texto(cliente, recebida.jid,
                     TEXTO_MENSAGEM_LONGA.format(limite=f"{entrada.MAX_CARACTERES:,}".replace(",", ".")), citar=citar)
        return "mensagem_longa"
    comando = _normalizar(texto)

    if comando in _NOVA:
        _conversa(dono, recebida.jid, nova=True)
        enviar_texto(cliente, recebida.jid, TEXTO_NOVA_CONVERSA, citar=citar)
        return "nova_conversa"

    conversa = _conversa(dono, recebida.jid)
    if comando in _FONTE:
        enviar_texto(cliente, recebida.jid, _texto_da_fonte(conversa), citar=citar)
        return "fonte"
    texto = _escolha_de_sugestao(conversa, texto) or texto
    anexo = {}
    if recebida.tipo in (entrada.IMAGEM, entrada.DOCUMENTO):
        try:
            anexo = preparar_anexo(recebida.arquivo_nome, cliente.baixar_midia(recebida.bruto))
        except AnexoRecusado as exc:
            enviar_texto(cliente, recebida.jid, str(exc), citar=citar)
            return "anexo_recusado"
        except WhatsAppIndisponivel:
            logger.warning("WhatsApp: não consegui baixar o arquivo", exc_info=True)
            enviar_texto(cliente, recebida.jid, "Não consegui abrir o arquivo. Pode mandar de novo?", citar=citar)
            return "anexo_indisponivel"
        texto = texto or TEXTO_ARQUIVO_SEM_PERGUNTA
    if not texto:
        return "vazia"

    mensagem, criada = ingest_inbound_message(conversa, InboundMessage(
        conversation_id=conversa.pk, client_message_id=recebida.id, text=texto,
        anexo_tipo=anexo.get("tipo", ""), anexo_nome=anexo.get("nome", ""),
        anexo_resumo=anexo.get("resumo", ""), anexo_token=anexo.get("token", ""),
    ))
    if not criada:
        return "repetida"     # a Evolution reentregou o mesmo evento
    Message.objects.filter(pk=mensagem.pk).update(autor_externo=recebida.numero, autor_nome=recebida.nome)

    # Para o aviso "Entendi: …" (whatsapp/aviso.py) saber onde responder.
    cache.set(f"whatsapp:pendente:{mensagem.pk}", {
        "jid": recebida.jid, "citar": citar.__dict__ if citar else None,
    }, timeout=SEGUNDOS_DO_PENDENTE)
    cliente.digitando(recebida.jid)

    executor = executor or get_configured_executor()
    reply = handle_message(
        mensagem, channel=WhatsAppChannel(),
        provider=provider or get_configured_provider(), executor=executor,
    )
    cache.delete(f"whatsapp:pendente:{mensagem.pk}")
    if not reply.reply_text:
        return "interrompida"
    resposta = mensagem.replies.order_by("-id").first()
    entregar(resposta, cliente, recebida.jid, citar=citar, executor=executor)
    return "respondida"


def _reacao(recebida) -> str:
    envio = (
        EnvioWhatsApp.objects.filter(externo_id=recebida.reacao_alvo, message__isnull=False)
        .select_related("message").first()
    )
    if envio is None or envio.message.in_reply_to_id is None:
        return "reacao_ignorada"
    if recebida.reacao in UTIL:
        nota = Avaliacao.Nota.UTIL
    elif recebida.reacao in ERRADA:
        nota = Avaliacao.Nota.ERRADA
    elif not recebida.reacao:
        Avaliacao.objects.filter(message=envio.message).delete()
        return "avaliacao_removida"
    else:
        return "reacao_ignorada"
    Avaliacao.objects.update_or_create(
        message=envio.message,
        defaults={"nota": nota, "caso_exportado_em": None,
                  "comentario": f"(reação no WhatsApp de {recebida.nome or recebida.numero or 'alguém'})"
                  if nota == Avaliacao.Nota.ERRADA else ""},
    )
    return "avaliacao"
