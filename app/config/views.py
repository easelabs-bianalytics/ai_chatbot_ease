from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Healthcheck da plataforma de deploy (ADR-0012).

    Única rota aberta sem login (ADR-0011), e não expõe nada. Não consulta o
    banco de propósito: se o Postgres piscar, a aplicação deve continuar de
    pé para responder quando ele voltar, em vez de a plataforma matar e
    recriar o container em laço.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)
