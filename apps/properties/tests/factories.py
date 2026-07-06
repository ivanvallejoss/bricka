import factory
from decimal import Decimal

from apps.contacts.tests.factories import UserFactory
from apps.properties.models import Property, ExternalPropertySource, PropertyMedia, Feature
from apps.properties.choices import PropertyType, PropertyStatus


class PropertyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Property

    property_type = PropertyType.APARTMENT
    address_line = factory.Sequence(lambda n: f"Calle {n} 123")
    city = "Resistencia"
    province = "Chaco"
    area_m2 = Decimal("80.00")
    is_external = False
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)


class ExternalPropertySourceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ExternalPropertySource

    property = factory.SubFactory(PropertyFactory, is_external=True)
    agency_name = factory.Sequence(lambda n: f"Agencia {n}")


class PropertyMediaFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PropertyMedia

    property = factory.SubFactory(PropertyFactory)
    r2_key = factory.Sequence(lambda n: f"media/properties/{n}/foto.jpg")
    mime_type = "image/jpeg"
    order = 0
    is_cover = False
    created_by = factory.SubFactory(UserFactory)


class FeatureFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Feature
        django_get_or_create = ("slug",)

    slug = factory.Sequence(lambda n: f"feature_{n}")
    label = factory.LazyAttribute(lambda o: o.slug.replace("_", " ").capitalize())
    is_active = True