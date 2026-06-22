from django.conf import settings
from django.http import HttpResponseRedirect


class BackofficeLoginRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path.startswith("/backoffice/")
            and not request.user.is_authenticated
        ):
            return HttpResponseRedirect(
                f"{settings.LOGIN_URL}?next={request.path}"
            )
        return self.get_response(request)