import factory
from decimal import Decimal

from apps.contacts.tests.factories import UserFactory
from apps.listings.models import Listing, ListingPublication
from apps.listings.choices import (
    Currency,
    ListingStatus,
    OperationType,
    PricePeriod,
    PublicationChannel,
    PublicationStatus,
)
from apps.properties.tests.factories import PropertyFactory


class ListingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Listing

    property = factory.SubFactory(PropertyFactory)
    operation_type = OperationType.RENT
    price = Decimal("50000.00")
    currency = Currency.ARS
    period = PricePeriod.MONTHLY
    status = ListingStatus.DRAFT
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)


class ListingPublicationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ListingPublication

    listing = factory.SubFactory(ListingFactory)
    channel = PublicationChannel.ZONAPROP
    status = PublicationStatus.PENDING
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)