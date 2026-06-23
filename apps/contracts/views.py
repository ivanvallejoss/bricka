from datetime import date

from django.http import Http404
from django.shortcuts import render

from .choices import ContractStatus
from .models import RentalContract
from .selectors import (
    ContractFilters,
    get_contract_list,
    get_contract_detail,
    get_adjustments_for_contract,
)
from apps.billing.selectors import (
    get_rental_payment_status,
    get_recent_documents_for_contract,
    get_billing_document_count_for_contract,
)


_PAYMENT_BADGE = {
    "paid":    {"text": "Pago",      "style": "success"},
    "pending": {"text": "Pendiente", "style": "warning"},
    "overdue": {"text": "En mora",   "style": "danger"},
}


def _build_adjustment_context(contract, today):
    """
    Contexto del banner de próximo ajuste.
    Separa la lógica de presentación de la view y el template.
    """
    days = (contract.next_adjustment_date - today).days
    if days < 0:
        abs_days = abs(days)
        return {
            "style": "danger",
            "text": f"Vencido hace {abs_days} día{'s' if abs_days != 1 else ''}",
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

    # El banner de ajuste solo aplica a contratos ACTIVE y SCHEDULED.
    # EXPIRED/TERMINATED: next_adjustment_date existe pero no es operativa.
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