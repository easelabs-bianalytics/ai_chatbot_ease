"""Interface web do chat (Fase 6, ADR-0007) e login (ADR-0011).

A página é uma só (`index.html` + `app.js`) e fala com a API do chat. O
login é por sessão do Django, a mesma do Admin: não existe senha em
`localStorage` nem token no navegador, e o cookie é `HttpOnly`.

Por isso o CSRF importa: a página recebe o cookie `csrftoken` ao carregar e
o `app.js` o devolve no cabeçalho `X-CSRFToken` em toda escrita — inclusive
no login, para ninguém conseguir logar o usuário numa conta alheia a partir
de outro site.
"""

from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

MENSAGEM_LOGIN_INVALIDO = "Usuário ou senha incorretos."


class _CsrfSempre(SessionAuthentication):
    """A autenticação de sessão do DRF só confere CSRF de quem já está
    logado. No login ninguém está — e é justamente onde o CSRF impede que
    outro site entre com a conta do atacante no navegador da vítima."""

    def authenticate(self, request):
        self.enforce_csrf(request)
        return None


def usuario_json(user) -> dict:
    nome = (user.get_full_name() or user.username).strip()
    partes = [p for p in nome.replace(".", " ").split() if p]
    iniciais = "".join(p[0] for p in partes[:2]).upper() or user.username[:2].upper()
    return {
        "usuario": user.username,
        "nome": nome,
        "iniciais": iniciais,
        # Quem administra vê custo e tokens na fonte da resposta; o restante
        # vê a consulta, a referência e o momento, que é o que dá confiança.
        "equipe": bool(user.is_staff),
    }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class IndexView(TemplateView):
    """A página do chat. Também atende as rotas do próprio app
    (`/conversas/12`), para um F5 não cair num 404."""

    template_name = "web/index.html"


class SessaoView(APIView):
    """Quem está logado. Aberta de propósito: é a primeira coisa que a página
    pergunta, antes de saber se mostra o login ou o chat."""

    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        if not request.user.is_authenticated:
            return Response({"autenticado": False})
        return Response({"autenticado": True, "usuario": usuario_json(request.user)})


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [_CsrfSempre]

    def post(self, request):
        usuario = str(request.data.get("usuario") or "").strip()
        senha = str(request.data.get("senha") or "")
        if not usuario or not senha:
            return Response(
                {"error": "Informe usuário e senha."}, status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(request, username=usuario, password=senha)
        if user is None or not user.is_active:
            # Mesma mensagem para usuário inexistente e senha errada: dizer
            # qual dos dois falhou ajudaria quem tenta adivinhar contas.
            return Response(
                {"error": MENSAGEM_LOGIN_INVALIDO}, status=status.HTTP_400_BAD_REQUEST
            )

        login(request, user)
        return Response({"autenticado": True, "usuario": usuario_json(user)})


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)
