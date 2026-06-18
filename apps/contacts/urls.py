from django.urls import path

from . import views

urlpatterns = [
    path("", views.contact_list, name="contact-list"),
    path("new/", views.contact_create, name="contact-create"),
    path("<uuid:contact_id>/", views.contact_detail, name="contact-detail"),
    path("<uuid:contact_id>/edit/", views.contact_edit, name="contact-edit"),
    path("<uuid:contact_id>/archive/", views.contact_archive, name="contact-archive"),
    path("<uuid:contact_id>/restore/", views.contact_restore, name="contact-restore"),
]