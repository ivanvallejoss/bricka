from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("backoffice/", include("apps.urls")),
    # path("webhooks/", include("apps.integrations.urls")),
    # path("", include("apps.portal.urls"))
]
