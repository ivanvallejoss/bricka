from datetime import date

from django.http import Http404, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse
from django.contrib import messages

from .choices import ContractStatus
from .exceptions import ContractDateConflict, ContractValidationError, InvalidContractStatus
from .forms import RentalContractForm
from .models import RentalContract
from .selectors import (
    ContractFilters,
    get_adjustments_for_contract,
    get_contract_detail,
    get_contract_list,
)
from .services import create_rental_contract, terminate_contract
from apps.billing.selectors import (
    get_billing_document_count_for_contract,
    get_recent_documents_for_contract,
    get_rental_payment_status,
)


_PAYMENT_BADGE = {
    "paid":    {"text": "Pago",      "style": "success"},
    "pending": {"text": "Pendiente", "style": "warning"},
    "overdue": {"text": "En mora",   "style": "danger"},
}


def _build_adjustment_context(contract, today):
    days = (contract.next_adjustment_date - today).days
    if days < 0:
        n = abs(days)
        return {
            "style": "danger",
            "text": f"Vencido hace {n} día{'s' if n != 1 else ''}",
            "subtext": contract.next_adjustment_date.strftime("%d/%m/%Y"),
        }
    if days == 0:
        return {
            "style": "warning",
            "text": "Hoy",
            "subtext": contract.next_adjustment_date.strftime("%d/%m/%Y"),
        }
    if days <= 30:
        return {
            "style": "warning",
            "text": f"En {days} día{'s' if days != 1 else ''}",
            "subtext": contract.next_adjustment_date.strftime("%d/%m/%Y"),
        }
    return {
        "style": "neutral",
        "text": contract.next_adjustment_date.strftime("%d/%m/%Y"),
        "subtext": f"En {days} días",
    }


def contract_list(request):
    section = request.GET.get("section")
    search = request.GET.get("q", "").strip() or None

    if section == "active":
        contracts = list(
            get_contract_list(ContractFilters(
                status=ContractStatus.ACTIVE,
                search=search,
            )).order_by("end_date")
        )
        payment_statuses = get_rental_payment_status(contracts, as_of=date.today())
        contexts = [
            {
                "contract": c,
                "payment_badge": _PAYMENT_BADGE.get(payment_statuses.get(c.id, "")),
            }
            for c in contracts
        ]
        return render(request, "contracts/partials/_section_active.html", {
            "contracts": contexts,
        })

    if section == "scheduled":
        today = date.today()
        contracts = list(
            get_contract_list(ContractFilters(
                status=ContractStatus.SCHEDULED,
                search=search,
            )).order_by("start_date")
        )
        contexts = [
            {
                "contract": c,
                "days_until_start": (c.start_date - today).days,
            }
            for c in contracts
        ]
        return render(request, "contracts/partials/_section_scheduled.html", {
            "contracts": contexts,
        })

    if section == "closed":
        contracts = get_contract_list(ContractFilters(
            statuses=[ContractStatus.EXPIRED, ContractStatus.TERMINATED],
            search=search,
        )).order_by("-end_date")
        return render(request, "contracts/partials/_section_closed.html", {
            "contracts": contracts,
        })

    return render(request, "contracts/contract_list.html", {})


def contract_detail(request, contract_id):
    try:
        contract = get_contract_detail(contract_id)
    except RentalContract.DoesNotExist:
        raise Http404

    today = date.today()
    adjustments = list(get_adjustments_for_contract(contract_id))
    recent_billing = list(get_recent_documents_for_contract(contract_id, limit=6))
    invoice_count = get_billing_document_count_for_contract(contract_id)
    payment_statuses = get_rental_payment_status([contract], as_of=today)
    payment_status = payment_statuses.get(contract.id)

    show_adjustment = contract.status in [
        ContractStatus.ACTIVE, ContractStatus.SCHEDULED
    ]
    adjustment_context = (
        _build_adjustment_context(contract, today) if show_adjustment else None
    )

    return render(request, "contracts/contract_detail.html", {
        "contract": contract,
        "adjustments": adjustments,
        "recent_billing": recent_billing,
        "invoice_count": invoice_count,
        "payment_status": payment_status,
        "adjustment_context": adjustment_context,
    })


def contract_create(request):
    if request.method == "POST":
        form = RentalContractForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            try:
                contract = create_rental_contract(
                    property_id=d["property_id"],
                    tenant_contact_id=d["tenant_contact_id"],
                    owner_contact_id=d["owner_contact_id"],
                    deal_id=d.get("deal_id"),
                    start_date=d["start_date"],
                    end_date=d["end_date"],
                    initial_price=d["initial_price"],
                    currency=d["currency"],
                    payment_due_day=d["payment_due_day"],
                    late_fee_percent_daily=d["late_fee_percent_daily"],
                    adjustment_index=d["adjustment_index"],
                    adjustment_percent=d.get("adjustment_percent"),
                    adjustment_frequency_months=d["adjustment_frequency_months"],
                    guarantee_type=d["guarantee_type"],
                    deposit_amount=d.get("deposit_amount"),
                    guarantee_detail=d.get("guarantee_detail", ""),
                    actor=request.user,
                )
            except ContractDateConflict as e:
                return render(request, "contracts/contract_create.html", {
                    "form": form,
                    "conflict_contract": e.conflicting_contract,
                })
            except ContractValidationError as e:
                form.add_error(None, str(e))
                return render(request, "contracts/contract_create.html", {"form": form})
            return redirect(reverse("contracts:detail", kwargs={"contract_id": contract.pk}))
        return render(request, "contracts/contract_create.html", {"form": form})

    return render(request, "contracts/contract_create.html", {"form": RentalContractForm()})



def contract_terminate(request, contract_id):
    if request.method == "POST":
        try:
            contract = get_contract_detail(contract_id)
        except RentalContract.DoesNotExist:
            raise Http404
        try:
            terminate_contract(contract=contract, actor=request.user)
            return redirect(reverse("contracts:list"))
        except InvalidContractStatus as e:
            messages.error(request, str(e))
            return redirect(
                reverse("contracts:detail", kwargs={"contract_id": contract_id})
            )
    return HttpResponseNotAllowed(["POST"])