from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import resolve_url

from django_htmx.http import HttpResponseClientRedirect


class BackofficeLoginRequiredMiddleware:
    """
    Protege todo /backoffice/ por prefijo de path. Invariante que
    sostiene: dentro del backoffice, request.user es siempre un User
    autenticado (actor= de los services nunca es anónimo).

    Única exención: la página de login (igualdad exacta contra
    LOGIN_URL resuelto). Logout y password-change quedan protegidos
    a propósito.

    Requests HTMX no reciben 302: fetch los sigue en silencio y HTMX
    swapearía el HTML del login dentro del target del partial. En su
    lugar, 200 + header HX-Redirect (HttpResponseClientRedirect), que
    HTMX interpreta como navegación de página completa. El next sale
    de la página real del usuario (current_url_abs_path), no del path
    del partial.

    Depende de HtmxMiddleware ANTES en la lista (request.htmx).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/backoffice/"):
            return self.get_response(request)

        if request.user.is_authenticated:
            return self.get_response(request)

        # resolve_url por request y no en __init__: al arrancar el
        # server, el URLconf puede no estar cargado todavía.
        login_url = resolve_url(settings.LOGIN_URL)

        if request.path == login_url:
            return self.get_response(request)

        if request.htmx:
            # None si el origen no coincide (anti open-redirect, capa 1;
            # LoginView re-valida el next al usarlo, capa 2).
            target = request.htmx.current_url_abs_path
            if target:
                return HttpResponseClientRedirect(
                    f"{login_url}?{urlencode({'next': target}, safe='/')}"
                )
            return HttpResponseClientRedirect(login_url)

        return HttpResponseRedirect(
            f"{login_url}?{urlencode({'next': request.path}, safe='/')}"
        )