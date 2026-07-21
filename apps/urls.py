from django.urls import include, path

from apps.properties import views as properties_views

urlpatterns = [
    path("", include("apps.users.urls")),
    path("contacts/", include("apps.contacts.urls")),
    path("properties/", include("apps.properties.urls")),
    path("contracts/", include("apps.contracts.urls")),
    path("billing/", include("apps.billing.urls")),
    path("geo/geocode/", properties_views.geocode, name="geocode"),
    # path("deals/", include("apps.deals.urls")),
    # path("listings/", include("apps.listings.urls")),
]