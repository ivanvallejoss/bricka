import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from apps.contracts.selectors import get_contract_detail, calculate_mora

from .choices import DocumentType, ConceptLineType
from .concept import ConceptLine
from .exceptions import BillingBusinessError, InvalidConceptLine
from .services import create_billing_document


_MONTH_NAMES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_VALID_TYPES_FROM_CONTRACT = {
    DocumentType.RENT_RECEIPT,
    DocumentType.EXPENSE_RECEIPT,
    DocumentType.OWNER_STATEMENT,
}


def _month_label(d: date) -> str:
    "devuelve la fecha en el idioma spanish"
    return f"{_MONTH_NAMES[d.month - 1]} {d.year}"


def _build_initial_lines(document_type: str, contract, mora, today: date) -> list[dict]:
    month = _month_label(today)
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
            {"type": ConceptLineType.RENT,         "label": "Alquiler",     "description": f"Alquiler {month}",    "amount": price,       "active": True,        "requires_description": False, "sign": 1},
            {"type": ConceptLineType.MORA,         "label": "Mora",         "description": mora_desc,              "amount": mora_amount, "active": mora_active, "requires_description": False, "sign": 1},
            {"type": ConceptLineType.ADJUSTMENT,   "label": "Ajuste",       "description": "Ajuste de precio",     "amount": "0.00",      "active": False,       "requires_description": False, "sign": 1},
            {"type": ConceptLineType.EXPENSE,      "label": "Expensas",     "description": "Expensas",             "amount": "0.00",      "active": False,       "requires_description": False, "sign": 1},
            {"type": ConceptLineType.OTHER_CHARGE, "label": "Otro (cargo)", "description": "",                     "amount": "0.00",      "active": False,       "requires_description": True,  "sign": 1},
            {"type": ConceptLineType.OTHER_CREDIT, "label": "Otro (haber)", "description": "",                     "amount": "0.00",      "active": False,       "requires_description": True,  "sign": -1},
        ]

    if document_type == DocumentType.EXPENSE_RECEIPT:
        return [
            {"type": ConceptLineType.EXPENSE,      "label": "Expensas",     "description": "Expensas",             "amount": "0.00",      "active": True,        "requires_description": False, "sign": 1},
            {"type": ConceptLineType.OTHER_CHARGE, "label": "Otro (cargo)", "description": "",                     "amount": "0.00",      "active": False,       "requires_description": True,  "sign": 1},
            {"type": ConceptLineType.OTHER_CREDIT, "label": "Otro (haber)", "description": "",                     "amount": "0.00",      "active": False,       "requires_description": True,  "sign": -1},
        ]

    # OWNER_STATEMENT — signos según _OWNER_STATEMENT_SIGN
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



def billing_list(request):
    return HttpResponse("billing_list — pendiente")


def emit_selector(request, contract_id):
    try:
        contract = get_contract_detail(contract_id)
    except ObjectDoesNotExist:
        raise Http404

    options = [
        {"type": DocumentType.RENT_RECEIPT,    "label": "Recibo de alquiler", "description": "Cobro mensual al inquilino",  "icon": "icons/receipt.html"},
        {"type": DocumentType.EXPENSE_RECEIPT, "label": "Recibo de gasto",    "description": "Expensas u otros gastos",     "icon": "icons/file-text.html"},
        {"type": DocumentType.OWNER_STATEMENT, "label": "Rendición de cuentas", "description": "Liquidación al propietario", "icon": "icons/dollar-sign.html"},
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

    # POST — procesar emisión
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
    return HttpResponse("document_detail — pendiente")


def document_cancel(request, document_id):
    return HttpResponse("document_cancel — pendiente")