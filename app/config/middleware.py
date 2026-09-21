from django.http import JsonResponse

CAMINHO_DE_SAUDE = "/api/health/"


class HealthCheckMiddleware:
    """Responde o health check antes de qualquer outra checagem.

    O ALB testa a saúde batendo direto no IP privado da task (target type
    `ip`), então o cabeçalho Host chega como `10.x.x.x:8000` — que nunca está
    no ALLOWED_HOSTS, feito de domínios. Sem isto o CommonMiddleware devolve
    400 e o alvo fica "unhealthy" para sempre, com a aplicação perfeita.

    Mesmo padrão do Cockpit (sales_force_crm/config/middleware.py): tem de
    ser a PRIMEIRA entrada de MIDDLEWARE. Não consulta o banco, pelo mesmo
    motivo da HealthView: se o Postgres piscar, a task não deve ser morta e
    recriada em laço.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == CAMINHO_DE_SAUDE:
            return JsonResponse({"status": "ok"})
        return self.get_response(request)
