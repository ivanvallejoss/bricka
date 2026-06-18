import uuid
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import pytest
from dateutil.relativedelta import relativedelta

from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.contracts.choices import AdjustmentIndex, ContractStatus
from apps.contracts.models import RentalContract
from apps.contracts.selectors import (
    ContractFilters,
    calculate_mora,
    get_active_contract_for_property,
    get_adjustments_for_contract,
    get_contract_detail,
    get_contract_list,
    get_contracts_due_for_activation,
    get_contracts_due_for_adjustment,
    get_contracts_due_for_expiration,
)
from apps.contracts.tests.factories import RentAdjustmentFactory, RentalContractFactory
from apps.properties.tests.factories import PropertyFactory


@pytest.mark.django_db
class TestGetContractList:
    def test_returns_all_contracts_without_filters(self):
        contract = RentalContractFactory()
        assert contract in get_contract_list()

    def test_filters_by_status(self):
        active = RentalContractFactory()
        scheduled = RentalContractFactory(scheduled=True)
        qs = get_contract_list(ContractFilters(status=ContractStatus.ACTIVE))
        assert active in qs
        assert scheduled not in qs

    def test_filters_by_property(self):
        prop = PropertyFactory()
        contract = RentalContractFactory(property=prop)
        other = RentalContractFactory()
        qs = get_contract_list(ContractFilters(property_id=prop.pk))
        assert contract in qs
        assert other not in qs

    def test_filters_by_tenant_contact(self):
        tenant = ContactFactory()
        contract = RentalContractFactory(tenant_contact=tenant)
        other = RentalContractFactory()
        qs = get_contract_list(ContractFilters(tenant_contact_id=tenant.pk))
        assert contract in qs
        assert other not in qs

    def test_filters_by_owner_contact(self):
        owner = ContactFactory()
        contract = RentalContractFactory(owner_contact=owner)
        other = RentalContractFactory()
        qs = get_contract_list(ContractFilters(owner_contact_id=owner.pk))
        assert contract in qs
        assert other not in qs

    def test_excludes_soft_deleted_contracts(self):
        actor = UserFactory()
        contract = RentalContractFactory(created_by=actor, updated_by=actor)
        contract.soft_delete(actor=actor)
        assert contract not in get_contract_list()


@pytest.mark.django_db
class TestGetContractDetail:
    def test_returns_contract_with_related_objects(self):
        contract = RentalContractFactory()
        result = get_contract_detail(contract.pk)
        assert result.property is not None
        assert result.tenant_contact is not None
        assert result.owner_contact is not None

    def test_raises_does_not_exist_for_unknown_id(self):
        with pytest.raises(RentalContract.DoesNotExist):
            get_contract_detail(uuid.uuid4())

    def test_raises_does_not_exist_for_soft_deleted_contract(self):
        actor = UserFactory()
        contract = RentalContractFactory(created_by=actor, updated_by=actor)
        contract.soft_delete(actor=actor)
        with pytest.raises(RentalContract.DoesNotExist):
            get_contract_detail(contract.pk)


@pytest.mark.django_db
class TestGetAdjustmentsForContract:
    def test_returns_adjustments_for_contract(self):
        contract = RentalContractFactory()
        adj = RentAdjustmentFactory(contract=contract)
        qs = get_adjustments_for_contract(contract.pk)
        assert adj in qs

    def test_excludes_adjustments_from_other_contracts(self):
        contract = RentalContractFactory()
        other = RentalContractFactory()
        RentAdjustmentFactory(contract=other)
        assert get_adjustments_for_contract(contract.pk).count() == 0


@pytest.mark.django_db
class TestGetActiveContractForProperty:
    def test_returns_active_contract(self):
        prop = PropertyFactory()
        contract = RentalContractFactory(property=prop, status=ContractStatus.ACTIVE)
        assert get_active_contract_for_property(prop.pk) == contract

    def test_returns_none_when_no_active_contract(self):
        prop = PropertyFactory()
        assert get_active_contract_for_property(prop.pk) is None

    def test_excludes_scheduled_contract(self):
        prop = PropertyFactory()
        RentalContractFactory(property=prop, scheduled=True)
        assert get_active_contract_for_property(prop.pk) is None


@pytest.mark.django_db
class TestGetContractsDueForExpiration:
    def test_returns_active_contract_with_past_end_date(self):
        contract = RentalContractFactory(
            status=ContractStatus.ACTIVE,
            end_date=date.today() - relativedelta(days=1),
        )
        assert contract in get_contracts_due_for_expiration(date.today())

    def test_excludes_contract_ending_today(self):
        contract = RentalContractFactory(
            status=ContractStatus.ACTIVE,
            end_date=date.today(),
        )
        assert contract not in get_contracts_due_for_expiration(date.today())

    def test_excludes_scheduled_contract_with_past_end_date(self):
        contract = RentalContractFactory(scheduled=True)
        assert contract not in get_contracts_due_for_expiration(date.today())


@pytest.mark.django_db
class TestGetContractsDueForActivation:
    def test_returns_scheduled_contract_with_start_date_today(self):
        contract = RentalContractFactory(
            status=ContractStatus.SCHEDULED,
            start_date=date.today(),
        )
        assert contract in get_contracts_due_for_activation(date.today())

    def test_returns_scheduled_contract_with_past_start_date(self):
        contract = RentalContractFactory(
            status=ContractStatus.SCHEDULED,
            start_date=date.today() - relativedelta(days=1),
        )
        assert contract in get_contracts_due_for_activation(date.today())

    def test_excludes_scheduled_contract_with_future_start_date(self):
        contract = RentalContractFactory(scheduled=True)
        assert contract not in get_contracts_due_for_activation(date.today())

    def test_excludes_active_contract(self):
        contract = RentalContractFactory(status=ContractStatus.ACTIVE)
        assert contract not in get_contracts_due_for_activation(date.today())


@pytest.mark.django_db
class TestGetContractsDueForAdjustment:
    def test_returns_active_contract_with_past_adjustment_date(self):
        contract = RentalContractFactory(
            status=ContractStatus.ACTIVE,
            next_adjustment_date=date.today() - relativedelta(days=1),
        )
        assert contract in get_contracts_due_for_adjustment(date.today())

    def test_returns_active_contract_with_adjustment_date_today(self):
        contract = RentalContractFactory(
            status=ContractStatus.ACTIVE,
            next_adjustment_date=date.today(),
        )
        assert contract in get_contracts_due_for_adjustment(date.today())

    def test_excludes_active_contract_with_future_adjustment_date(self):
        contract = RentalContractFactory(
            status=ContractStatus.ACTIVE,
            next_adjustment_date=date.today() + relativedelta(days=1),
        )
        assert contract not in get_contracts_due_for_adjustment(date.today())

    def test_excludes_scheduled_contract(self):
        contract = RentalContractFactory(
            scheduled=True,
            next_adjustment_date=date.today(),
        )
        assert contract not in get_contracts_due_for_adjustment(date.today())


@pytest.mark.django_db
class TestCalculateMora:
    def test_returns_none_when_not_overdue(self):
        contract = RentalContractFactory(payment_due_day=10)
        as_of = date(2025, 6, 9)
        assert calculate_mora(contract, as_of=as_of) is None

    def test_returns_none_on_due_date(self):
        contract = RentalContractFactory(payment_due_day=10)
        as_of = date(2025, 6, 10)
        assert calculate_mora(contract, as_of=as_of) is None

    def test_returns_calculation_when_overdue(self):
        contract = RentalContractFactory(
            payment_due_day=10,
            current_price=Decimal("50000.00"),
            late_fee_percent_daily=Decimal("2.00"),
        )
        as_of = date(2025, 6, 15)  # 5 días de mora
        result = calculate_mora(contract, as_of=as_of)

        assert result is not None
        assert result.days_overdue == 5
        assert result.daily_rate == Decimal("2.00")

        expected = (
            Decimal("50000.00")
            * ((Decimal("1") + Decimal("2.00") / Decimal("100")) ** 5 - Decimal("1"))
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        assert result.total_amount == expected

    def test_mora_increases_with_days(self):
        contract = RentalContractFactory(
            payment_due_day=10,
            current_price=Decimal("50000.00"),
            late_fee_percent_daily=Decimal("2.00"),
        )
        result_5 = calculate_mora(contract, as_of=date(2025, 6, 15))
        result_10 = calculate_mora(contract, as_of=date(2025, 6, 20))
        assert result_10.total_amount > result_5.total_amount