import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.contracts.selectors import calculate_mora, get_contract_detail

from .choices import ConceptLineType, DocumentType
from .concept import ConceptLine
from .exceptions import BillingBusinessError, CannotCancelDocument, InvalidConceptLine
from .display import enrich_lines_for_display, month_label
from .selectors import get_billing_document, get_cobros, get_pagos
from .services import cancel_billing_document, create_billing_document


_VALID_TYPES_FROM_CONTRACT = {
    DocumentType.RENT_RECEIPT,
    DocumentType.EXPENSE_RECEIPT,
    DocumentType.OWNER_STATEMENT,
}

def _build_initial_lines(document_type: str, contract, mora, today: date) -> list[dict]:
    month = month_label(today)
    price = str(contract.current_price)

    if document_type == DocumentType.RENT_RECEIPT:
        mora_active = mora is not None
        mora_amount = str(mora.total_amount) if mora else "0.00"
        mora_desc = (
            f"Mora {mora.days_overdue} día{'s' if mora.days_overdue != 1 else ''}"
            f" @ {mora.daily_rate}% diario"
            if mora else "Mora"
        )
        return [
            {"type": ConceptLineType.RENT,         "label": "Alquiler",     "description": f"Alquiler {month}",  "amount": price,       "active": True,        "requires_description": False, "sign": 1},
            {"type": ConceptLineType.MORA,         "label": "Mora",         "description": mora_desc,            "amount": mora_amount, "active": mora_active, "requires_description": False, "sign": 1},
            {"type": ConceptLineType.ADJUSTMENT,   "label": "Ajuste",       "description": "Ajuste de precio",   "amount": "0.00",      "active": False,       "requires_description": False, "sign": 1},
            {"type": ConceptLineType.EXPENSE,      "label": "Expensas",     "description": "Expensas",           "amount": "0.00",      "active": False,       "requires_description": False, "sign": 1},
            {"type": ConceptLineType.OTHER_CHARGE, "label": "Otro (cargo)", "description": "",                   "amount": "0.00",      "active": False,       "requires_description": True,  "sign": 1},
            {"type": ConceptLineType.OTHER_CREDIT, "label": "Otro (haber)", "description": "",                   "amount": "0.00",      "active": False,       "requires_description": True,  "sign": -1},
        ]

    if document_type == DocumentType.EXPENSE_RECEIPT:
        return [
            {"type": ConceptLineType.EXPENSE,      "label": "Expensas",     "description": "Expensas",           "amount": "0.00",      "active": True,        "requires_description": False, "sign": 1},
            {"type": ConceptLineType.OTHER_CHARGE, "label": "Otro (cargo)", "description": "",                   "amount": "0.00",      "active": False,       "requires_description": True,  "sign": 1},
            {"type": ConceptLineType.OTHER_CREDIT, "label": "Otro (haber)", "description": "",                   "amount": "0.00",      "active": False,       "requires_description": True,  "sign": -1},
        ]

    return [
        {"type": ConceptLineType.RENT,         "label": "Alquiler",                   "description": f"Alquiler {month}",          "amount": price,  "active": True,  "requires_description": False, "sign": 1},
        {"type": ConceptLineType.COMMISSION,   "label": "Comisión de administración", "description": "Comisión de administración", "amount": "0.00", "active": False, "requires_description": False, "sign": -1},
        {"type": ConceptLineType.EXPENSE,      "label": "Expensas",                   "description": "Expensas",                   "amount": "0.00", "active": False, "requires_description": False, "sign": -1},
        {"type": ConceptLineType.OTHER_CHARGE, "label": "Otro (cargo)",               "description": "",                           "amount": "0.00", "active": False, "requires_description": True,  "sign": -1},
        {"type": ConceptLineType.OTHER_CREDIT, "label": "Otro (haber)",               "description": "",                           "amount": "0.00", "active": False, "requires_description": True,  "sign": 1},
    ]


def _render_emit_form(request, contract, document_type, today, error=None, period_str=None):
    mora = (
        calculate_mora(contract, as_of=today)
        if document_type == DocumentType.RENT_RECEIPT
        else None
    )
    return render(request, "billing/partials/_emit_form.html", {
        "contract": contract,
        "document_type": document_type,
        "document_type_label": DocumentType(document_type).label,
        "initial_lines_json": json.dumps(_build_initial_lines(document_type, contract, mora, today)),
        "mora": mora,
        "current_month": period_str or today.strftime("%Y-%m"),
        "error": error,
    })


def emit_selector(request, contract_id):
    try:
        contract = get_contract_detail(contract_id)
    except ObjectDoesNotExist:
        raise Http404

    options = [
        {"type": DocumentType.RENT_RECEIPT,    "label": "Recibo de alquiler",   "description": "Cobro mensual al inquilino",  "icon": "icons/receipt.html"},
        {"type": DocumentType.EXPENSE_RECEIPT, "label": "Recibo de gasto",      "description": "Expensas u otros gastos",     "icon": "icons/file-text.html"},
        {"type": DocumentType.OWNER_STATEMENT, "label": "Rendición de cuentas", "description": "Liquidación al propietario",  "icon": "icons/dollar-sign.html"},
    ]
    return render(request, "billing/partials/_emit_modal.html", {
        "contract": contract,
        "options": options,
    })


def emit_form(request, contract_id, document_type):
    if document_type not in _VALID_TYPES_FROM_CONTRACT:
        raise Http404

    try:
        contract = get_contract_detail(contract_id)
    except ObjectDoesNotExist:
        raise Http404

    today = date.today()

    if request.method == "GET":
        return _render_emit_form(request, contract, document_type, today)

    period_str = request.POST.get("period", "")
    try:
        year, month = period_str.split("-")
        period = date(int(year), int(month), 1)
    except (ValueError, AttributeError):
        return _render_emit_form(
            request, contract, document_type, today,
            error="El período seleccionado no es válido.",
            period_str=period_str,
        )

    try:
        lines_data = json.loads(request.POST.get("lines_json", "[]"))
        lines = []
        for line_data in lines_data:
            contract_id_for_line = None
            if (
                document_type == DocumentType.OWNER_STATEMENT
                and line_data["type"] not in {
                    ConceptLineType.OTHER_CHARGE,
                    ConceptLineType.OTHER_CREDIT,
                }
            ):
                contract_id_for_line = str(contract.pk)
            lines.append(ConceptLine(
                type=line_data["type"],
                description=line_data.get("description", ""),
                amount=Decimal(str(line_data["amount"])),
                contract_id=contract_id_for_line,
            ))
    except (InvalidConceptLine, KeyError, ValueError, InvalidOperation, json.JSONDecodeError) as e:
        return _render_emit_form(
            request, contract, document_type, today,
            error=str(e), period_str=period_str,
        )

    service_contract = None if document_type == DocumentType.OWNER_STATEMENT else contract
    recipient_contact = (
        contract.owner_contact
        if document_type == DocumentType.OWNER_STATEMENT
        else None
    )

    try:
        create_billing_document(
            document_type=document_type,
            lines=lines,
            date=today,
            period=period,
            contract=service_contract,
            recipient_contact=recipient_contact,
            actor=request.user,
        )
    except BillingBusinessError as e:
        return _render_emit_form(
            request, contract, document_type, today,
            error=str(e), period_str=period_str,
        )

    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse(
        "contracts:detail", kwargs={"contract_id": str(contract.pk)}
    )
    return response


def document_detail(request, document_id):
    try:
        document = get_billing_document(document_id)
    except ObjectDoesNotExist:
        raise Http404

    return render(request, "billing/partials/_document_detail_modal.html", {
        "document": document,
        "enriched_lines": enrich_lines_for_display(document),
    })


def document_cancel(request, document_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        document = get_billing_document(document_id)
    except ObjectDoesNotExist:
        raise Http404

    try:
        cancel_billing_document(document=document, actor=request.user)
    except CannotCancelDocument:
        pass  # unreachable en flujo normal — la UI no muestra el botón si ya está cancelado

    if document.contract:
        return redirect(
            reverse("contracts:detail", kwargs={"contract_id": str(document.contract.pk)})
        )
    return redirect(reverse("billing:list"))


def billing_list(request):
    section = request.GET.get("section")
    search = request.GET.get("q", "").strip() or None
    period_str = request.GET.get("period", "")
    page = int(request.GET.get("page", 1))

    period = None
    if period_str:
        try:
            year, month = period_str.split("-")
            period = date(int(year), int(month), 1)
        except (ValueError, AttributeError):
            period = None

    if section == "cobros":
        page_obj = get_cobros(search=search, period=period, page=page)
        return render(request, "billing/partials/_section_cobros.html", {
            "page_obj": page_obj,
            "search": search or "",
            "period_str": period_str,
        })

    if section == "pagos":
        page_obj = get_pagos(search=search, period=period, page=page)
        return render(request, "billing/partials/_section_pagos.html", {
            "page_obj": page_obj,
            "search": search or "",
            "period_str": period_str,
        })

    return render(request, "billing/billing_list.html", {})