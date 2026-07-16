import factory
from decimal import Decimal

from apps.contacts.tests.factories import UserFactory
from apps.properties.models import Property, ExternalPropertySource, PropertyMedia, Feature
from apps.properties.choices import PropertyType, PropertyStatus, FeatureCategory


class PropertyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Property
        skip_postgeneration_save = True

    class Params:
        # Propiedad que satisface el gate de publicación (descripción + foto).
        # El default de la factory sigue siendo "operable, no publicable" —
        # el trait se pide explícito donde el test va a publicar.
        publishable = factory.Trait(
            # Descripción ≥150 chars + 5 fotos: satisface el gate 5/150 (S3a).
            description=(
                "Departamento de dos ambientes al frente, muy luminoso, con "
                "balcón corrido, cocina integrada equipada, piso de parquet y "
                "excelente ventilación cruzada. A metros del transporte y "
                "comercios. Ideal para vivienda o renta. Apto crédito."
            ),
            gate_media=factory.RelatedFactoryList(
                "apps.properties.tests.factories.PropertyMediaFactory",
                factory_related_name="property",
                size=5,
            ),
        )

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
    category = FeatureCategory.CARACTERISTICAS
    is_active = True