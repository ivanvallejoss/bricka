from datetime import date
from decimal import Decimal
from uuid import uuid4

from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction

from apps.billing.choices import ConceptLineType, DocumentStatus, DocumentType
from apps.billing.concept import ConceptLine
from apps.billing.exceptions import (
    DuplicatePeriodicReceipt,
    InvalidConceptLine,
    InvalidLineTypeForDocument,
    MissingPeriod,
    MissingRecipient,
    MissingRequiredRelation,
)
from apps.billing.services import create_billing_document
from apps.billing.tests.factories import BillingDocumentFactory
from apps.contacts.tests.factories import ContactFactory
from apps.contracts.choices import ContractStatus
from apps.contracts.tests.factories import RentalContractFactory
from apps.deals.tests.factories import DealFactory

pytestmark = pytest.mark.django_db


def _line(type_, amount="1000.00", description="", contract_id=None):
    return ConceptLine(
        type=type_, description=description, amount=Decimal(amount), contract_id=contract_id
    )


class TestRelationPresence:
    """Presencia de FK por tipo — invariante en el service, no en DB."""

    def test_rent_receipt_requires_contract(self):
        with pytest.raises(MissingRequiredRelation):
            create_billing_document(
                document_type=DocumentType.RENT_RECEIPT,
                lines=[_line(ConceptLineType.RENT)],
                date=date(2026, 6, 1),
                period=date(2026, 6, 1),
            )

    def test_expense_receipt_requires_contract(self):
        with pytest.raises(MissingRequiredRelation):
            create_billing_document(
                document_type=DocumentType.EXPENSE_RECEIPT,
                lines=[_line(ConceptLineType.EXPENSE)],
                date=date(2026, 6, 1),
            )

    def test_commission_receipt_requires_deal(self):
        with pytest.raises(MissingRequiredRelation):
            create_billing_document(
                document_type=DocumentType.COMMISSION_RECEIPT,
                lines=[_line(ConceptLineType.COMMISSION)],
                date=date(2026, 6, 1),
                recipient_contact=ContactFactory(),
            )

    def test_owner_statement_rejects_contract(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        with pytest.raises(MissingRequiredRelation):
            create_billing_document(
                document_type=DocumentType.OWNER_STATEMENT,
                lines=[_line(ConceptLineType.RENT, contract_id=str(contract.id))],
                date=date(2026, 6, 1),
                period=date(2026, 6, 1),
                contract=contract,
                recipient_contact=ContactFactory(),
            )

    def test_owner_statement_rejects_deal(self):
        deal = DealFactory()
        with pytest.raises(MissingRequiredRelation):
            create_billing_document(
                document_type=DocumentType.OWNER_STATEMENT,
                lines=[_line(ConceptLineType.RENT)],
                date=date(2026, 6, 1),
                period=date(2026, 6, 1),
                deal=deal,
                recipient_contact=ContactFactory(),
            )


class TestPeriodResolution:
    def test_rent_receipt_requires_period(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        with pytest.raises(MissingPeriod):
            create_billing_document(
                document_type=DocumentType.RENT_RECEIPT,
                lines=[_line(ConceptLineType.RENT)],
                date=date(2026, 6, 15),
                contract=contract,
            )

    def test_expense_receipt_requires_period(self):
        """EXPENSE_RECEIPT pasó a _PERIOD_REQUIRED en la corrección post-auditoría
        (es periódico cuando la inmobiliaria administra expensas — mismo riesgo
        de doble-emisión que RENT_RECEIPT). Reemplaza al test que afirmaba que
        EXPENSE_RECEIPT no requería period.
        """
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        with pytest.raises(MissingPeriod):
            create_billing_document(
                document_type=DocumentType.EXPENSE_RECEIPT,
                lines=[_line(ConceptLineType.EXPENSE)],
                date=date(2026, 6, 15),
                contract=contract,
            )

    def test_period_normalizes_to_first_of_month(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        document = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[_line(ConceptLineType.RENT)],
            date=date(2026, 6, 15),
            period=date(2026, 6, 23),
            contract=contract,
        )
        assert document.period == date(2026, 6, 1)


class TestRecipientResolution:
    def test_rent_receipt_recipient_is_tenant(self):
        tenant = ContactFactory()
        contract = RentalContractFactory(status=ContractStatus.ACTIVE, tenant_contact=tenant)
        document = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[_line(ConceptLineType.RENT)],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            contract=contract,
        )
        assert document.recipient_contact_id == tenant.id

    def test_commission_receipt_requires_explicit_recipient(self):
        deal = DealFactory()
        with pytest.raises(MissingRecipient):
            create_billing_document(
                document_type=DocumentType.COMMISSION_RECEIPT,
                lines=[_line(ConceptLineType.COMMISSION)],
                date=date(2026, 6, 1),
                deal=deal,
            )

    def test_owner_statement_requires_explicit_recipient(self):
        with pytest.raises(MissingRecipient):
            create_billing_document(
                document_type=DocumentType.OWNER_STATEMENT,
                lines=[_line(ConceptLineType.RENT)],
                date=date(2026, 6, 1),
                period=date(2026, 6, 1),
            )


class TestLineValidation:
    def test_empty_lines_rejected(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        with pytest.raises(InvalidConceptLine):
            create_billing_document(
                document_type=DocumentType.RENT_RECEIPT,
                lines=[],
                date=date(2026, 6, 1),
                period=date(2026, 6, 1),
                contract=contract,
            )

    def test_commission_line_rejected_in_rent_receipt(self):
        """El caso que el briefing pedía evitar explícitamente."""
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        with pytest.raises(InvalidLineTypeForDocument):
            create_billing_document(
                document_type=DocumentType.RENT_RECEIPT,
                lines=[_line(ConceptLineType.COMMISSION)],
                date=date(2026, 6, 1),
                period=date(2026, 6, 1),
                contract=contract,
            )

    def test_owner_statement_line_requires_contract_id(self):
        with pytest.raises(InvalidConceptLine):
            create_billing_document(
                document_type=DocumentType.OWNER_STATEMENT,
                lines=[_line(ConceptLineType.RENT, contract_id=None)],
                date=date(2026, 6, 1),
                period=date(2026, 6, 1),
                recipient_contact=ContactFactory(),
            )

    def test_owner_statement_other_charge_does_not_require_contract_id(self):
        document = create_billing_document(
            document_type=DocumentType.OWNER_STATEMENT,
            lines=[_line(ConceptLineType.OTHER_CHARGE, description="Reparación")],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            recipient_contact=ContactFactory(),
        )
        assert document.total_amount == Decimal("-1000.00")

    def test_other_line_without_description_rejected_at_dataclass_level(self):
        with pytest.raises(InvalidConceptLine):
            ConceptLine(type=ConceptLineType.OTHER_CHARGE, description="", amount=Decimal("100"))

    def test_non_positive_amount_rejected_at_dataclass_level(self):
        with pytest.raises(InvalidConceptLine):
            ConceptLine(type=ConceptLineType.RENT, description="x", amount=Decimal("0"))


class TestTotalComputation:
    """La matriz de signos se discutió y se modificó tres veces en esta
    sesión. Estos tests existen para que un cuarto cambio no pase
    desapercibido — son la red, no documentación.
    """

    def test_rent_receipt_sums_all_lines(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        document = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[
                _line(ConceptLineType.RENT, "1000"),
                _line(ConceptLineType.MORA, "50"),
                _line(ConceptLineType.OTHER_CHARGE, "20", description="Sellado"),
            ],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            contract=contract,
        )
        assert document.total_amount == Decimal("1070.00")

    def test_rent_receipt_other_credit_subtracts(self):
        """OTHER_CREDIT = descuento al inquilino. Resta incluso en un recibo."""
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        document = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[
                _line(ConceptLineType.RENT, "1000"),
                _line(ConceptLineType.OTHER_CREDIT, "100", description="Descuento"),
            ],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            contract=contract,
        )
        assert document.total_amount == Decimal("900.00")

    def test_owner_statement_deducts_commission_and_expense(self):
        cid = str(uuid4())
        document = create_billing_document(
            document_type=DocumentType.OWNER_STATEMENT,
            lines=[
                _line(ConceptLineType.RENT, "1000", contract_id=cid),
                _line(ConceptLineType.MORA, "50", contract_id=cid),
                _line(ConceptLineType.COMMISSION, "100", contract_id=cid),
                _line(ConceptLineType.EXPENSE, "30", contract_id=cid),
            ],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            recipient_contact=ContactFactory(),
        )
        # 1000 + 50 (cobrado) - 100 - 30 (deducciones de la agencia) = 920
        assert document.total_amount == Decimal("920.00")

    def test_owner_statement_other_charge_subtracts(self):
        """Óptica final acordada: OTHER_CHARGE = la agencia le carga
        algo al propietario → resta de su neto."""
        document = create_billing_document(
            document_type=DocumentType.OWNER_STATEMENT,
            lines=[_line(ConceptLineType.OTHER_CHARGE, "200", description="Costo de reparación")],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            recipient_contact=ContactFactory(),
        )
        assert document.total_amount == Decimal("-200.00")

    def test_owner_statement_other_credit_adds(self):
        """OTHER_CREDIT = haber a favor del propietario → suma."""
        document = create_billing_document(
            document_type=DocumentType.OWNER_STATEMENT,
            lines=[_line(ConceptLineType.OTHER_CREDIT, "150", description="Ajuste a favor")],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            recipient_contact=ContactFactory(),
        )
        assert document.total_amount == Decimal("150.00")

    def test_owner_statement_total_can_be_negative(self):
        """Permitido y documentado: si las deducciones superan lo cobrado."""
        cid = str(uuid4())
        document = create_billing_document(
            document_type=DocumentType.OWNER_STATEMENT,
            lines=[
                _line(ConceptLineType.RENT, "500", contract_id=cid),
                _line(ConceptLineType.COMMISSION, "300", contract_id=cid),
                _line(ConceptLineType.EXPENSE, "400", contract_id=cid),
            ],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            recipient_contact=ContactFactory(),
        )
        assert document.total_amount == Decimal("-200.00")


class TestDuplicatePeriodicReceiptGuard:
    def test_blocks_second_issued_receipt_same_period(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[_line(ConceptLineType.RENT)],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            contract=contract,
        )
        with pytest.raises(DuplicatePeriodicReceipt):
            create_billing_document(
                document_type=DocumentType.RENT_RECEIPT,
                lines=[_line(ConceptLineType.RENT)],
                date=date(2026, 6, 5),
                period=date(2026, 6, 1),
                contract=contract,
            )

    def test_allows_reissue_after_cancellation(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        first = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[_line(ConceptLineType.RENT)],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            contract=contract,
        )
        first.status = DocumentStatus.CANCELLED
        first.save(update_fields=["status", "updated_at"])

        second = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[_line(ConceptLineType.RENT)],
            date=date(2026, 6, 10),
            period=date(2026, 6, 1),
            contract=contract,
        )
        assert second.status == DocumentStatus.ISSUED

    def test_different_periods_do_not_collide(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[_line(ConceptLineType.RENT)],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            contract=contract,
        )
        document = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[_line(ConceptLineType.RENT)],
            date=date(2026, 7, 1),
            period=date(2026, 7, 1),
            contract=contract,
        )
        assert document.period == date(2026, 7, 1)

    def test_partial_index_is_the_real_backstop(self):
        """El guard del service es un SELECT previo — no cierra la carrera
        entre dos requests concurrentes. El índice parcial sí. Este test
        lo ejercita directo en DB, bypaseando el service.
        """
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        BillingDocumentFactory(
            document_type=DocumentType.RENT_RECEIPT,
            status=DocumentStatus.ISSUED,
            contract=contract,
            period=date(2026, 6, 1),
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                BillingDocumentFactory(
                    document_type=DocumentType.RENT_RECEIPT,
                    status=DocumentStatus.ISSUED,
                    contract=contract,
                    period=date(2026, 6, 1),
                )

class TestDuplicatePeriodicReceiptRaceCondition:
    def test_integrity_error_translated_to_business_exception(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        BillingDocumentFactory(
            document_type=DocumentType.RENT_RECEIPT,
            status=DocumentStatus.ISSUED,
            contract=contract,
            period=date(2026, 6, 1),
        )
        with patch("apps.billing.services.BillingDocument.objects.filter") as mock_filter:
            mock_filter.return_value.exists.return_value = False  # simula el guard "ciego" a la carrera
            with pytest.raises(DuplicatePeriodicReceipt):
                create_billing_document(
                    document_type=DocumentType.RENT_RECEIPT,
                    lines=[_line(ConceptLineType.RENT)],
                    date=date(2026, 6, 10),
                    period=date(2026, 6, 1),
                    contract=contract,
                )

class TestRecipientSnapshot:
    def test_recipient_identity_is_frozen_at_emission(self):
        tenant = ContactFactory(full_name="Juan Pérez", document_number="12345678")
        contract = RentalContractFactory(status=ContractStatus.ACTIVE, tenant_contact=tenant)
        document = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[_line(ConceptLineType.RENT)],
            date=date(2026, 6, 1),
            period=date(2026, 6, 1),
            contract=contract,
        )
        assert document.recipient_name == "Juan Pérez"
        assert document.recipient_document_number == "12345678"

        # El contacto cambia datos DESPUÉS de emitido — el comprobante no debe enterarse.
        tenant.full_name = "Juan Pérez (actualizado)"
        tenant.document_number = "99999999"
        tenant.save(update_fields=["full_name", "document_number", "updated_at"])

        document.refresh_from_db()
        assert document.recipient_name == "Juan Pérez"
        assert document.recipient_document_number == "12345678"