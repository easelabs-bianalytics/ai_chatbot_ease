from django.db import models


class CodigoDeAcesso(models.Model):
    """Um código de 6 dígitos enviado ao e-mail corporativo para entrar.

    Guarda o hash, nunca o código: quem lê o banco não entra por ele. Cada
    linha também é a trilha de acesso — quem pediu, quando, de que IP, se
    usou e quantas vezes errou — que é o que o time de BI consulta quando
    precisa saber quem esteve no app.
    """

    email = models.EmailField(db_index=True)
    codigo_hash = models.CharField(max_length=64)
    criado_em = models.DateTimeField(auto_now_add=True, db_index=True)
    expira_em = models.DateTimeField()
    tentativas = models.PositiveSmallIntegerField(default=0)
    # Uso bem-sucedido. Um código usado não entra de novo.
    usado_em = models.DateTimeField(null=True, blank=True)
    # Anulado por um código mais novo para o mesmo e-mail ou por tentativas
    # demais. Separado de `usado_em` para a trilha dizer qual dos dois foi.
    anulado_em = models.DateTimeField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    navegador = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-criado_em"]
        verbose_name = "código de acesso"
        verbose_name_plural = "códigos de acesso"

    def __str__(self):
        return f"{self.email} · {self.criado_em:%d/%m/%Y %H:%M}"

    @property
    def situacao(self) -> str:
        if self.usado_em:
            return "usado"
        if self.anulado_em:
            return "anulado"
        return "pendente"
