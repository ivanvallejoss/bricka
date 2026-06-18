from django.urls import path
from . import views

app_name = "properties"

urlpatterns = [
    path("", views.property_list, name="list"),
    path("<uuid:pk>/slide-over/", views.property_slide_over, name="slide_over"),
    path("<uuid:pk>/slide-over/publications/", views.slide_over_publications, name="slide_over_publications"),
    path("<uuid:pk>/slide-over/billing/", views.slide_over_billing, name="slide_over_billing"),
    path("<uuid:pk>/slide-over/contacts/", views.slide_over_contacts, name="slide_over_contacts"),
    path("<uuid:pk>/slide-over/documents/", views.slide_over_documents, name="slide_over_documents"),
    path("<uuid:pk>/", views.property_detail, name="detail"), 
    path("<uuid:pk>/publications/", views.detail_publications, name="detail_publications"),
    path("<uuid:pk>/documents/", views.detail_documents, name="detail_documents"),
]