from django.urls import path
from . import views

app_name = "contracts"

urlpatterns = [
    path("", views.contract_list, name="list"),
    path("new/", views.contract_create, name="create"),
    path("<uuid:contract_id>/", views.contract_detail, name="detail"),
    path("<uuid:contract_id>/terminate/", views.contract_terminate, name="terminate")
]