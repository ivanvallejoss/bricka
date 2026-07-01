from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pytest
from dateutil.relativedelta import relativedelta

from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.contracts.choices import AdjustmentIndex, ContractStatus, GuaranteeType
from apps.contracts.exceptions import (
    ContractDateConflict,
    ContractValidationError,
    InvalidContractStatus,
)
from apps.contracts.models import RentAdjustment
from apps.contracts.services import (
    activate_scheduled_contract,
    apply_rent_adjustment,
    create_rental_contract,
    expire_contract,
    terminate_contract,
    update_contract_end_date,
)
from apps.contracts.tests.factories import RentalContractFactory

from apps.listings.choices import ListingStatus, OperationType
from apps.listings.tests.factories import ListingFactory

from apps.properties.choices import PropertyStatus
from apps.properties.tests.factories import PropertyFactory


def _base_contract_kwargs(prop, tenant, owner, actor, **overrides):
    """Kwargs base para create_rental_contract — evita repetición en tests."""
    defaults = dict(
        property_id=prop.pk,
        tenant_contact_id=tenant.pk,
        owner_contact_id=owner.pk,
        start_date=date.today(),
        end_date=date.today() + relativedelta(months=12),
        initial_price=Decimal("50000.00"),
        currency="ARS",
        payment_due_day=10,
        adjustment_index=AdjustmentIndex.ICL,
        adjustment_frequency_months=3,
        guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
        actor=actor,
    )
    defaults.update(overrides)
    return defaults


@pytest.mark.django_db
class TestCreateRentalContract:
    def test_create_active_contract_when_start_date_is_today(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        tenant = ContactFactory()
        owner = ContactFactory()

        contract = create_rental_contract(
            **_base_contract_kwargs(prop, tenant, owner, actor)
        )

        assert contract.status == ContractStatus.ACTIVE
        assert contract.current_price == Decimal("50000.00")
        assert contract.created_by == actor

    def test_active_contract_updates_property_to_rented(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        tenant = ContactFactory()
        owner = ContactFactory()

        create_rental_contract(**_base_contract_kwargs(prop, tenant, owner, actor))

        prop.refresh_from_db()
        assert prop.status == PropertyStatus.RENTED

    def test_create_scheduled_contract_when_start_date_is_future(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        tenant = ContactFactory()
        owner = ContactFactory()

        contract = create_rental_contract(**_base_contract_kwargs(
            prop, tenant, owner, actor,
            start_date=date.today() + relativedelta(months=1),
            end_date=date.today() + relativedelta(months=13),
        ))

        assert contract.status == ContractStatus.SCHEDULED

    def test_scheduled_contract_does_not_update_property_status(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        tenant = ContactFactory()
        owner = ContactFactory()

        create_rental_contract(**_base_contract_kwargs(
            prop, tenant, owner, actor,
            start_date=date.today() + relativedelta(months=1),
            end_date=date.today() + relativedelta(months=13),
        ))

        prop.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE

    def test_raises_date_conflict_with_overlapping_contract(self):
        actor = UserFactory()
        prop = PropertyFactory()
        tenant = ContactFactory()
        owner = ContactFactory()
        RentalContractFactory(
            property=prop,
            status=ContractStatus.ACTIVE,
            start_date=date.today() - relativedelta(months=1),
            end_date=date.today() + relativedelta(months=11),
        )

        with pytest.raises(ContractDateConflict):
            create_rental_contract(**_base_contract_kwargs(prop, tenant, owner, actor))

    def test_raises_validation_error_when_fixed_percent_without_amount(self):
        actor = UserFactory()
        prop = PropertyFactory()
        tenant = ContactFactory()
        owner = ContactFactory()

        with pytest.raises(ContractValidationError):
            create_rental_contract(**_base_contract_kwargs(
                prop, tenant, owner, actor,
                adjustment_index=AdjustmentIndex.FIXED_PERCENT,
                adjustment_percent=None,
            ))

    def test_calculates_next_adjustment_date_from_start_date(self):
        actor = UserFactory()
        prop = PropertyFactory()
        tenant = ContactFactory()
        owner = ContactFactory()

        contract = create_rental_contract(**_base_contract_kwargs(
            prop, tenant, owner, actor,
            start_date=date.today(),
            adjustment_frequency_months=3,
        ))

        expected = date.today() + relativedelta(months=3)
        assert contract.next_adjustment_date == expected

    def test_allows_scheduled_contract_after_existing_active_contract(self):
        actor = UserFactory()
        prop = PropertyFactory()
        tenant = ContactFactory()
        owner = ContactFactory()
        RentalContractFactory(
            property=prop,
            status=ContractStatus.ACTIVE,
            start_date=date.today() - relativedelta(months=1),
            end_date=date.today() + relativedelta(months=11),
        )

        # Nuevo contrato empieza después de que el activo termina
        contract = create_rental_contract(**_base_contract_kwargs(
            prop, tenant, owner, actor,
            start_date=date.today() + relativedelta(months=12),
            end_date=date.today() + relativedelta(months=24),
        ))

        assert contract.status == ContractStatus.SCHEDULED


@pytest.mark.django_db
class TestTerminateContract:
    def test_terminate_active_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(created_by=actor, updated_by=actor)
        terminate_contract(contract=contract, actor=actor)
        contract.refresh_from_db()
        assert contract.status == ContractStatus.TERMINATED

    def test_terminate_active_contract_updates_property_to_available(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.RENTED)
        contract = RentalContractFactory(
            property=prop,
            status=ContractStatus.ACTIVE,
            created_by=actor,
            updated_by=actor,
        )
        terminate_contract(contract=contract, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE

    def test_terminate_scheduled_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            scheduled=True,
            created_by=actor,
            updated_by=actor,
        )
        terminate_contract(contract=contract, actor=actor)
        contract.refresh_from_db()
        assert contract.status == ContractStatus.TERMINATED

    def test_terminate_scheduled_contract_does_not_update_property_status(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        contract = RentalContractFactory(
            property=prop,
            scheduled=True,
            created_by=actor,
            updated_by=actor,
        )
        terminate_contract(contract=contract, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE

    def test_terminate_raises_for_expired_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            expired=True,
            created_by=actor,
            updated_by=actor,
        )
        with pytest.raises(InvalidContractStatus):
            terminate_contract(contract=contract, actor=actor)

    def test_terminate_raises_for_terminated_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            terminated=True,
            created_by=actor,
            updated_by=actor,
        )
        with pytest.raises(InvalidContractStatus):
            terminate_contract(contract=contract, actor=actor)


@pytest.mark.django_db
class TestExpireContract:
    def test_expire_active_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(created_by=actor, updated_by=actor)
        expire_contract(contract=contract, actor=actor)
        contract.refresh_from_db()
        assert contract.status == ContractStatus.EXPIRED

    def test_expire_active_contract_updates_property_to_available(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.RENTED)
        contract = RentalContractFactory(
            property=prop,
            status=ContractStatus.ACTIVE,
            created_by=actor,
            updated_by=actor,
        )
        expire_contract(contract=contract, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.AVAILABLE

    def test_expire_raises_for_scheduled_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            scheduled=True,
            created_by=actor,
            updated_by=actor,
        )
        with pytest.raises(InvalidContractStatus):
            expire_contract(contract=contract, actor=actor)

    def test_expire_raises_for_already_expired_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            expired=True,
            created_by=actor,
            updated_by=actor,
        )
        with pytest.raises(InvalidContractStatus):
            expire_contract(contract=contract, actor=actor)

    def test_expire_accepts_none_actor_for_celery(self):
        contract = RentalContractFactory()
        result = expire_contract(contract=contract, actor=None)
        assert result.status == ContractStatus.EXPIRED


@pytest.mark.django_db
class TestActivateScheduledContract:
    def test_activate_scheduled_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            scheduled=True,
            created_by=actor,
            updated_by=actor,
        )
        activate_scheduled_contract(contract=contract, actor=actor)
        contract.refresh_from_db()
        assert contract.status == ContractStatus.ACTIVE

    def test_activate_updates_property_to_rented(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        contract = RentalContractFactory(
            property=prop,
            scheduled=True,
            created_by=actor,
            updated_by=actor,
        )
        activate_scheduled_contract(contract=contract, actor=actor)
        prop.refresh_from_db()
        assert prop.status == PropertyStatus.RENTED

    def test_activate_raises_for_active_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(created_by=actor, updated_by=actor)
        with pytest.raises(InvalidContractStatus):
            activate_scheduled_contract(contract=contract, actor=actor)

    def test_activate_accepts_none_actor_for_celery(self):
        contract = RentalContractFactory(scheduled=True)
        result = activate_scheduled_contract(contract=contract, actor=None)
        assert result.status == ContractStatus.ACTIVE


@pytest.mark.django_db
class TestApplyRentAdjustment:
    def test_apply_adjustment_updates_current_price(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            current_price=Decimal("50000.00"),
            created_by=actor,
            updated_by=actor,
        )
        apply_rent_adjustment(
            contract=contract,
            adjustment_date=date.today(),
            index_value_at_date=Decimal("15.00"),
            applied_by=actor,
        )
        contract.refresh_from_db()
        expected = (
            Decimal("50000.00") * (Decimal("1") + Decimal("15.00") / Decimal("100"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)  # noqa: F401 - imported via decimal
        # Usamos: from decimal import ROUND_HALF_UP al inicio del archivo
        assert contract.current_price == expected

    def test_apply_adjustment_creates_rent_adjustment_record(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            current_price=Decimal("50000.00"),
            adjustment_index=AdjustmentIndex.ICL,
            created_by=actor,
            updated_by=actor,
        )
        apply_rent_adjustment(
            contract=contract,
            adjustment_date=date.today(),
            index_value_at_date=Decimal("15.00"),
            applied_by=actor,
        )
        adj = RentAdjustment.objects.get(contract=contract)
        assert adj.previous_price == Decimal("50000.00")
        assert adj.index_used == AdjustmentIndex.ICL
        assert adj.index_value_at_date == Decimal("15.00")
        assert adj.applied_by == actor

    def test_apply_adjustment_advances_next_adjustment_date(self):
        actor = UserFactory()
        original_next = date(2025, 3, 1)
        contract = RentalContractFactory(
            next_adjustment_date=original_next,
            adjustment_frequency_months=3,
            created_by=actor,
            updated_by=actor,
        )
        apply_rent_adjustment(
            contract=contract,
            adjustment_date=date.today(),
            index_value_at_date=Decimal("10.00"),
            applied_by=actor,
        )
        contract.refresh_from_db()
        assert contract.next_adjustment_date == date(2025, 6, 1)

    def test_apply_adjustment_raises_for_non_active_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            scheduled=True,
            created_by=actor,
            updated_by=actor,
        )
        with pytest.raises(InvalidContractStatus):
            apply_rent_adjustment(
                contract=contract,
                adjustment_date=date.today(),
                index_value_at_date=Decimal("10.00"),
                applied_by=actor,
            )


@pytest.mark.django_db
class TestUpdateContractEndDate:
    def test_extend_contract_end_date(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            end_date=date.today() + relativedelta(months=6),
            created_by=actor,
            updated_by=actor,
        )
        new_end = date.today() + relativedelta(months=12)
        update_contract_end_date(contract=contract, new_end_date=new_end, actor=actor)
        contract.refresh_from_db()
        assert contract.end_date == new_end

    def test_shorten_contract_end_date(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            end_date=date.today() + relativedelta(months=12),
            created_by=actor,
            updated_by=actor,
        )
        new_end = date.today() + relativedelta(months=3)
        update_contract_end_date(contract=contract, new_end_date=new_end, actor=actor)
        contract.refresh_from_db()
        assert contract.end_date == new_end

    def test_update_scheduled_contract_end_date(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            scheduled=True,
            created_by=actor,
            updated_by=actor,
        )
        new_end = date.today() + relativedelta(months=14)
        update_contract_end_date(contract=contract, new_end_date=new_end, actor=actor)
        contract.refresh_from_db()
        assert contract.end_date == new_end

    def test_raises_for_past_end_date(self):
        actor = UserFactory()
        contract = RentalContractFactory(created_by=actor, updated_by=actor)
        with pytest.raises(ContractValidationError):
            update_contract_end_date(
                contract=contract,
                new_end_date=date.today(),
                actor=actor,
            )

    def test_raises_for_end_date_before_start_date(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            start_date=date.today() + relativedelta(months=2),
            end_date=date.today() + relativedelta(months=14),
            status=ContractStatus.SCHEDULED,
            created_by=actor,
            updated_by=actor,
        )
        with pytest.raises(ContractValidationError):
            update_contract_end_date(
                contract=contract,
                new_end_date=date.today() + relativedelta(months=1),
                actor=actor,
            )

    def test_raises_date_conflict_with_other_contract(self):
        actor = UserFactory()
        prop = PropertyFactory()
        contract_a = RentalContractFactory(
            property=prop,
            status=ContractStatus.ACTIVE,
            start_date=date.today() - relativedelta(months=1),
            end_date=date.today() + relativedelta(months=5),
            created_by=actor,
            updated_by=actor,
        )
        # Contract B empieza justo después de que A termina — sin solapamiento
        RentalContractFactory(
            property=prop,
            scheduled=True,
            start_date=date.today() + relativedelta(months=6),
            end_date=date.today() + relativedelta(months=18),
        )
        # Intentamos extender A para que solape con B
        with pytest.raises(ContractDateConflict):
            update_contract_end_date(
                contract=contract_a,
                new_end_date=date.today() + relativedelta(months=7),
                actor=actor,
            )

    def test_raises_for_expired_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(
            expired=True,
            created_by=actor,
            updated_by=actor,
        )
        with pytest.raises(InvalidContractStatus):
            update_contract_end_date(
                contract=contract,
                new_end_date=date.today() + relativedelta(months=6),
                actor=actor,
            )


@pytest.mark.django_db
class TestCreateRentalContractListingReconciliation:
    """
    Wiring: create_rental_contract (ACTIVE) enruta por el orquestador, que cierra
    el listing de alquiler y deja el de venta. Detalle de la cascada en
    apps/operations/tests.
    """

    def test_active_contract_closes_rent_listing_leaves_sale(self):
        actor = UserFactory()
        prop = PropertyFactory(status=PropertyStatus.AVAILABLE)
        tenant = ContactFactory()
        owner = ContactFactory()
        sale = ListingFactory(
            property=prop,
            operation_type=OperationType.SALE,
            status=ListingStatus.PUBLISHED,
        )
        rent = ListingFactory(
            property=prop,
            operation_type=OperationType.RENT,
            status=ListingStatus.PUBLISHED,
        )
        create_rental_contract(**_base_contract_kwargs(prop, tenant, owner, actor))
        sale.refresh_from_db()
        rent.refresh_from_db()
        assert rent.status == ListingStatus.CLOSED
        assert sale.status == ListingStatus.PUBLISHED