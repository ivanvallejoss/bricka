from django.urls import path
from . import views

app_name = "properties"

urlpatterns = [
    path("", views.property_list, name="list"),
    path("search/", views.property_search, name="search"),
    path("new/", views.property_new, name="new"),
    path("<uuid:pk>/slide-over/", views.property_slide_over, name="slide_over"),
    path("<uuid:pk>/slide-over/publications/", views.slide_over_publications, name="slide_over_publications"),
    path("<uuid:pk>/slide-over/billing/", views.slide_over_billing, name="slide_over_billing"),
    path("<uuid:pk>/slide-over/contacts/", views.slide_over_contacts, name="slide_over_contacts"),
    path("<uuid:pk>/slide-over/documents/", views.slide_over_documents, name="slide_over_documents"),
    path("<uuid:pk>/", views.property_detail, name="detail"), 
    path("<uuid:pk>/edit/", views.property_edit, name="edit"),
    path("<uuid:pk>/new/detalle/", views.property_new_detalle, name="new_detalle"),
    path("<uuid:pk>/new/fotos/", views.property_new_fotos, name="new_fotos"),
    path("<uuid:pk>/new/operacion/", views.property_new_operacion, name="new_operacion"),
    path("<uuid:pk>/external-source/", views.external_source_update, name="external_source_update"),
    path("<uuid:pk>/listings/", views.listing_create, name="listing_create"),
    path("<uuid:pk>/listings/<uuid:listing_id>/publish/", views.listing_publish, name="listing_publish"),
    path("<uuid:pk>/listings/<uuid:listing_id>/price/", views.listing_price, name="listing_price"),
    path("<uuid:pk>/publications/", views.detail_publication, name="detail_publication"),
    path("<uuid:pk>/documents/", views.detail_documents, name="detail_documents"),
    path("<uuid:pk>/media/sign/", views.media_sign, name="media_sign"),
    path("<uuid:pk>/media/confirm/", views.media_confirm, name="media_confirm"),
    path("<uuid:pk>/media/reorder/", views.media_reorder, name="media_reorder"),
    path("media/<uuid:id>/set-cover/", views.media_set_cover, name="media_set_cover"),
    path("media/<uuid:id>/delete/", views.media_delete, name="media_delete"),
]