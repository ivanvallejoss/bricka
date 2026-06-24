from django.urls import include, path

urlpatterns = [
    path("contacts/", include("apps.contacts.urls")),
    path("properties/", include("apps.properties.urls")),
    path("contracts/", include("apps.contracts.urls")),
    path("billing/", include("apps.billing.urls")),
    # path("deals/", include("apps.deals.urls")),
    # path("listings/", include("apps.listings.urls")),
]