import factory

from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.deals.choices import DealType
from apps.deals.models import Deal
from apps.listings.tests.factories import ListingFactory


class DealFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Deal

    deal_type = DealType.SALE
    client_contact = factory.SubFactory(ContactFactory)
    listing = None
    external_property_notes = "Propiedad externa — factory default"
    outcome = ""
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)

    class Params:
        with_listing = factory.Trait(
            listing=factory.SubFactory(ListingFactory),
            external_property_notes="",
        )