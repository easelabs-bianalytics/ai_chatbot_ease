from django.apps import AppConfig


class WhatsAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "whatsapp"
    verbose_name = "WhatsApp"

    def ready(self):
        # O aviso "Entendi: …" sai quando o orquestrador registra o que
        # entendeu (ADR-0028). Ligado aqui para o orquestrador não conhecer o
        # WhatsApp.
        from whatsapp import aviso  # noqa: F401
