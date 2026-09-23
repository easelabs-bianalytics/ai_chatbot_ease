"""Webhook da Evolution e a página de conexão no Admin (ADR-0028)."""

import hmac
import logging

from django.contrib import admin
from django.core.cache import cache
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from whatsapp import config, servicos, tasks
from whatsapp.cliente import EvolutionCliente, WhatsAppIndisponivel, cliente_configurado
from whatsapp.models import ContatoWhatsApp, GrupoWhatsApp

logger = logging.getLogger(__name__)


class WebhookView(APIView):
    """Recebe os eventos da Evolution.

    Três travas antes de qualquer trabalho:

    - o segredo no caminho (a Evolution não manda cabeçalho próprio no
      webhook, como já era na referência), comparado em tempo constante;
    - sem segredo configurado, recusa tudo;
    - com WHATSAPP_WEBHOOK_SO_LOCAL=1, pedido que passou por proxy (traz
      `X-Forwarded-For`) é recusado. Em produção fica 0: a Evolution é outro
      service e volta pelo ALB.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, token):
        esperado = config.token_do_webhook()
        if not esperado or not hmac.compare_digest(str(token), esperado):
            return Response(status=status.HTTP_404_NOT_FOUND)
        if request.META.get("HTTP_X_FORWARDED_FOR") and config.webhook_so_local():
            logger.warning("WhatsApp: webhook chamado de fora da task; recusado")
            return Response(status=status.HTTP_404_NOT_FOUND)
        payload = request.data if isinstance(request.data, dict) else {}
        if servicos.parar_se_pedido(payload):
            return Response({"ok": True})
        tasks.receber.delay(payload)
        return Response({"ok": True})


@staff_member_required
def conexao(request):
    """Estado da conexão, QR para parear e botão de configurar a instância.

    A Evolution não fica exposta: o QR chega aqui, pelo Admin, com o login de
    sempre."""
    cliente = cliente_configurado()
    contexto = {**admin.site.each_context(request), "title": "Conexão do WhatsApp",
                "configurada": isinstance(cliente, EvolutionCliente),
                "numero": config.numero_do_jarvis(), "lid": config.lid_do_jarvis(),
                "contatos": ContatoWhatsApp.objects.filter(ativo=True).count(),
                "grupos": GrupoWhatsApp.objects.filter(ativo=True).count(),
                "webhook": bool(config.token_do_webhook())}
    try:
        if request.method == "POST" and request.POST.get("acao") == "configurar":
            cliente.configurar(config.url_interna_do_webhook())
            contexto["mensagem"] = "Instância configurada: grupos ligados, chamadas recusadas, webhook apontado."
        contexto.update(cliente.estado())
        contexto["mencoes"] = cache.get(servicos.CHAVE_DAS_MENCOES) or []
        if contexto.get("estado") == "open":
            # Para liberar um grupo é preciso o identificador dele: a lista
            # mostra os grupos do número e quais já estão liberados.
            liberados = set(GrupoWhatsApp.objects.filter(ativo=True).values_list("jid", flat=True))
            try:
                contexto["grupos_do_numero"] = [{**g, "liberado": g["jid"] in liberados} for g in cliente.grupos()]
            except WhatsAppIndisponivel:
                # A lista é ajuda para o cadastro: sem ela, o resto da página vale.
                contexto["grupos_do_numero"] = []
        if contexto.get("estado") not in ("open",) and request.GET.get("qr"):
            contexto.update(cliente.conectar())
    except WhatsAppIndisponivel as exc:
        contexto["erro"] = f"A Evolution não respondeu: {exc}"
    return render(request, "whatsapp/conexao.html", contexto)
