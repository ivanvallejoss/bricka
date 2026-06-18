import factory
from decimal import Decimal
from django.utils import timezone

from apps.common.choices import Currency

from ..choices import ConceptLineType, DocumentStatus, DocumentType
from ..models import BillingDocument


class BillingDocumentFactory(factory.django.DjangoModelFactory):
    """Construye filas de BillingDocument DIRECTAMENTE — sin pasar por
    create_billing_document. Uso: arrange de fixtures para tests de
    selectors (badge, listados), donde lo que se testea NO es el service.

    El service mismo se ejercita llamándolo de forma explícita en
    test_services.py — este factory nunca lo invoca, así que no sirve
    para validar sus invariantes (presencia de FK, total derivado, etc.).

    number usa su propio contador global desacoplado de las PostgreSQL
    sequences reales — solo necesita ser único, no continuo ni realista.
    """

    class Meta:
        model = BillingDocument

    document_type = DocumentType.RENT_RECEIPT
    number = factory.Sequence(lambda n: n + 1)
    date = factory.LazyFunction(lambda: timezone.now().date())
    period = factory.LazyAttribute(lambda o: o.date.replace(day=1))
    total_amount = factory.LazyFunction(lambda: Decimal("1000.00"))
    currency = Currency.ARS
    concept = factory.LazyFunction(lambda: [
        {
            "type": ConceptLineType.RENT,
            "description": "Alquiler",
            "amount": "1000.00",
            "contract_id": None,
        }
    ])
    recipient_contact = factory.SubFactory(
        "apps.contacts.tests.factories.ContactFactory"
    )
    recipient_name = factory.LazyAttribute(lambda o: o.recipient_contact.full_name)
    recipient_document_type = factory.LazyAttribute(lambda o: o.recipient_contact.document_type)
    recipient_document_number = factory.LazyAttribute(lambda o: o.recipient_contact.document_number)
    status = DocumentStatus.ISSUED
    contract = None
    deal = None
    created_by = None