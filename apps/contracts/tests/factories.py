import factory
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from apps.common.choices import Currency
from apps.contacts.tests.factories import ContactFactory, UserFactory
from apps.contracts.choices import AdjustmentIndex, ContractStatus, GuaranteeType
from apps.contracts.models import RentalContract, RentAdjustment
from apps.properties.tests.factories import PropertyFactory


class RentalContractFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RentalContract

    property = factory.SubFactory(PropertyFactory)
    tenant_contact = factory.SubFactory(ContactFactory)
    owner_contact = factory.SubFactory(ContactFactory)
    start_date = factory.LazyFunction(lambda: date.today() - relativedelta(months=1))
    end_date = factory.LazyFunction(lambda: date.today() + relativedelta(months=11))
    initial_price = Decimal("50000.00")
    current_price = Decimal("50000.00")
    currency = Currency.ARS
    payment_due_day = 10
    late_fee_percent_daily = Decimal("2.00")
    adjustment_index = AdjustmentIndex.ICL
    adjustment_frequency_months = 3
    next_adjustment_date = factory.LazyFunction(
        lambda: date.today() + relativedelta(months=2)
    )
    guarantee_type = GuaranteeType.PROPERTY_GUARANTEE
    status = ContractStatus.ACTIVE
    created_by = factory.SubFactory(UserFactory)
    updated_by = factory.SubFactory(UserFactory)

    class Params:
        scheduled = factory.Trait(
            status=ContractStatus.SCHEDULED,
            start_date=factory.LazyFunction(
                lambda: date.today() + relativedelta(months=1)
            ),
            end_date=factory.LazyFunction(
                lambda: date.today() + relativedelta(months=13)
            ),
            next_adjustment_date=factory.LazyFunction(
                lambda: date.today() + relativedelta(months=4)
            ),
        )
        expired = factory.Trait(
            status=ContractStatus.EXPIRED,
            start_date=factory.LazyFunction(
                lambda: date.today() - relativedelta(months=13)
            ),
            end_date=factory.LazyFunction(
                lambda: date.today() - relativedelta(months=1)
            ),
        )
        terminated = factory.Trait(
            status=ContractStatus.TERMINATED,
        )


class RentAdjustmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RentAdjustment

    contract = factory.SubFactory(RentalContractFactory)
    adjustment_date = factory.LazyFunction(date.today)
    previous_price = Decimal("50000.00")
    new_price = Decimal("57500.00")
    index_used = AdjustmentIndex.ICL
    index_value_at_date = Decimal("15.00")
    applied_by = factory.SubFactory(UserFactory)