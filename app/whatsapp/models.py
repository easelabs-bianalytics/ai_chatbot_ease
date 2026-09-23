"""Quem pode falar com o Jarvis pelo WhatsApp, e o que ele mandou (ADR-0028).

O número do Jarvis é um número de WhatsApp como outro qualquer: qualquer
pessoa que o tenha pode escrever, e qualquer grupo pode incluí-lo. Na
referência isso já fez a IA responder em grupos reais por engano. Aqui a
trava é o cadastro: só fala com o Jarvis o número ou o grupo liberado no
Admin. O resto é ignorado em silêncio.
"""

import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models, transaction


def so_digitos(numero: str) -> str:
    return re.sub(r"\D", "", str(numero or ""))


class ContatoWhatsApp(models.Model):
    """Um número liberado para conversar com o Jarvis no individual.

    O número é de uma pessoa que já tem usuário no Jarvis: a conversa do
    WhatsApp aparece na lista dela no chat web, com a mesma cota e a mesma
    auditoria."""

    numero = models.CharField(
        max_length=20, unique=True,
        help_text="Com DDI e DDD, só dígitos: 5511999998888.",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contatos_whatsapp",
        verbose_name="usuário",
    )
    ativo = models.BooleanField(default=True)
    observacao = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username"]
        verbose_name = "contato do WhatsApp"
        verbose_name_plural = "contatos do WhatsApp"

    def save(self, *args, **kwargs):
        self.numero = so_digitos(self.numero)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.numero} ({self.user})"


class GrupoWhatsApp(models.Model):
    """Um grupo em que o Jarvis responde quando é marcado (@jarvis).

    Qualquer membro pode chamar (decisão de 2026-09-23): liberar o grupo é
    decidir que todos os membros veem dados de negócio. A conversa é de um
    usuário técnico do grupo, sem login, e a cota é a do grupo."""

    jid = models.CharField(
        max_length=80, unique=True,
        help_text="Identificador do grupo no WhatsApp (termina em @g.us). Aparece no log e na página de conexão.",
    )
    nome = models.CharField(max_length=120)
    ativo = models.BooleanField(default=True)
    limite_diario = models.PositiveIntegerField(default=30)
    limite_semanal = models.PositiveIntegerField(default=150)
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="grupo_whatsapp",
        null=True, blank=True, editable=False,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "grupo do WhatsApp"
        verbose_name_plural = "grupos do WhatsApp"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.usuario_id is None:
                User = get_user_model()
                tecnico = User(username=f"whatsapp-grupo-{so_digitos(self.jid)[:40] or 'novo'}", is_active=True)
                # Usuário técnico: sem senha e sem e-mail, ninguém entra com
                # ele no chat web (o login é por código no e-mail).
                tecnico.set_unusable_password()
                tecnico.save()
                self.usuario = tecnico
            super().save(*args, **kwargs)

    def __str__(self):
        return self.nome


class EnvioWhatsApp(models.Model):
    """Uma mensagem que o Jarvis mandou no WhatsApp.

    Uma resposta pode sair em várias (texto, gráfico, planilha). Guardar o id
    de cada uma é o que permite ligar de volta ao Jarvis a reação 👍/👎 e a
    resposta citando a mensagem dele (é assim que o grupo chama o Jarvis sem
    marcar de novo)."""

    class Tipo(models.TextChoices):
        TEXTO = "texto", "Texto"
        IMAGEM = "imagem", "Imagem"
        DOCUMENTO = "documento", "Documento"
        AVISO = "aviso", "Aviso"

    message = models.ForeignKey(
        "messaging.Message", on_delete=models.CASCADE, related_name="envios_whatsapp", null=True, blank=True,
    )
    externo_id = models.CharField(max_length=100, unique=True)
    jid = models.CharField(max_length=80)
    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "envio no WhatsApp"
        verbose_name_plural = "envios no WhatsApp"

    def __str__(self):
        return f"{self.get_tipo_display()} {self.externo_id}"
