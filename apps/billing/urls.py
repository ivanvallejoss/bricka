from django.urls import path
from . import views

app_name = "billing"

urlpatterns = [
    # Vista global — historial completo
    path("", views.billing_list, name="list"),

    # Emisión desde contrato — two-step modal
    path(
        "emit/<uuid:contract_id>/",
        views.emit_selector,
        name="emit-selector",
    ),
    path(
        "emit/<uuid:contract_id>/<str:document_type>/",
        views.emit_form,
        name="emit-form",
    ),

    # Comprobante individual
    path("<uuid:document_id>/", views.document_detail, name="detail"),
    path("<uuid:document_id>/cancel/", views.document_cancel, name="cancel"),
]