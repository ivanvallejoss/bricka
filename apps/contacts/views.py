import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import redirect, render
from django.urls import reverse

from .choices import ContactRole, ContactSource
from .exceptions import ContactHasOpenDeals
from .forms import ContactForm
from .models import Contact
from .selectors import (
    ContactFilters, 
    get_contact_detail, 
    get_contact_history, 
    get_contact_list,
    get_contacts_for_search,
    )
from .services import archive_contact, create_contact, restore_contact, update_contact
from .selectors import get_search_preferences_for_contact

from apps.billing.selectors import get_recent_documents_for_contact

from apps.contracts.selectors import get_contract_list, ContractFilters

from apps.common.storage import generate_document_download_url

from apps.documents.selectors import get_document_list, DocumentFilters
from apps.documents.context import DocumentContext
from apps.documents.utils import categorize_document

from apps.properties.selectors import get_properties_for_owner


def contact_list(request):
    """
    Lista de contactos con filtros opcionales por query params.

    Full page  → contacts/contact_list.html
                Extiende base.html. Incluye layout completo.

    HTMX       → contacts/partials/contact_list_table.html
                Solo la tabla + paginación. Sin layout.
                Target esperado: #contact-list-container
    """
    filters = ContactFilters(
        role=request.GET.get("role") or None,
        source=request.GET.get("source") or None,
        assigned_agent_id=request.GET.get("assigned_agent_id") or None,
        search=request.GET.get("q") or None,
    )
    context = {
        "contacts": get_contact_list(filters=filters),
        "filters": filters,
        "role_choices": ContactRole.choices,
        "source_choices": ContactSource.choices,
    }
    if request.htmx:
        return render(request, "contacts/partials/contact_list_table.html", context)
    return render(request, "contacts/contact_list.html", context)


def contact_detail(request, contact_id):
    """
    Detalle de un contacto activo con historial de audit.

    Full page  → contacts/contact_detail.html
                Extiende base.html. Incluye layout completo.

    HTMX       → contacts/partials/contact_detail_panel.html
                Solo el panel de detalle. Sin layout.
                Target esperado: #main-content
    """
    try:
        contact = get_contact_detail(contact_id)
    except Contact.DoesNotExist:
        raise Http404

    owned_properties = get_properties_for_owner(contact_id=contact_id)
    tenant_contracts = get_contract_list(ContractFilters(tenant_contact_id=contact_id))

    raw_documents = get_document_list(DocumentFilters(contact_id=contact_id))
    documents = [
        DocumentContext(
            document=doc,
            signed_url=generate_document_download_url(doc.r2_key),
            file_category=categorize_document(doc.content_type),
        )
        for doc in raw_documents
    ]

    search_preferences = get_search_preferences_for_contact(contact_id=contact_id)

    recent_billing = list(get_recent_documents_for_contact(contact_id))

    context = {
        "contact": contact,
        "owned_properties": owned_properties,
        "tenant_contracts": tenant_contracts,
        "documents": documents,
        "search_preferences": search_preferences,
        "recent_billing": recent_billing,
    }
    if request.htmx:
        return render(request, "contacts/partials/contact_detail_panel.html", context)
    return render(request, "contacts/contact_detail.html", context)


def contact_create(request):
    """
    Formulario de creación de contacto.

    Full page  → contacts/contact_form.html
                Extiende base.html.

    HTMX GET   → contacts/partials/contact_form_modal.html
                Formulario vacío para renderizar dentro de un modal.
                Target esperado: #modal-container

    HTMX POST éxito  → HX-Redirect a contact-detail del nuevo contacto.
    HTMX POST error  → contacts/partials/contact_form_modal.html
                    con errores de validación inline.
                    Target esperado: #modal-container
    """
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            contact = create_contact(
                full_name=d["full_name"],
                contact_type=d["contact_type"],
                email=d["email"],
                phone=d["phone"],
                document_type=d["document_type"],
                document_number=d["document_number"],
                role=d["role"],
                source=d["source"],
                source_detail=d["source_detail"],
                assigned_agent=d["assigned_agent"],
                notes=d["notes"],
                actor=request.user,
            )
            if request.htmx:
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse(
                    "contacts:contact-detail", kwargs={"contact_id": contact.pk}
                )
                return response
            return redirect(reverse("contacts:contact-detail", kwargs={"contact_id": contact.pk}))
        if request.htmx:
            return render(request, "contacts/partials/contact_form_modal.html", {
                "form": form,
                "is_create": True,
            })
    else:
        form = ContactForm()

    if request.htmx:
        return render(request, "contacts/partials/contact_form_modal.html", {
            "form": form,
            "is_create": True,
        })
    return render(request, "contacts/contact_form.html", {
        "form": form,
        "is_create": True,
    })


def contact_edit(request, contact_id):
    """
    Formulario de edición de contacto existente.

    Full page  → contacts/contact_form.html
                Extiende base.html.

    HTMX GET   → contacts/partials/contact_form_modal.html
                Formulario con instancia para renderizar en modal.
                Target esperado: #modal-container

    HTMX POST éxito  → HX-Redirect a contact-detail.
    HTMX POST error  → contacts/partials/contact_form_modal.html
                    con errores de validación inline.
    """
    try:
        contact = get_contact_detail(contact_id)
    except Contact.DoesNotExist:
        raise Http404

    if request.method == "POST":
        form = ContactForm(request.POST, instance=contact)
        if form.is_valid():
            d = form.cleaned_data
            update_contact(
                contact,
                full_name=d["full_name"],
                contact_type=d["contact_type"],
                email=d["email"],
                phone=d["phone"],
                document_type=d["document_type"],
                document_number=d["document_number"],
                role=d["role"],
                source=d["source"],
                source_detail=d["source_detail"],
                assigned_agent=d["assigned_agent"],
                notes=d["notes"],
                actor=request.user,
            )
            if request.htmx:
                response = HttpResponse(status=204)
                response["HX-Redirect"] = reverse(
                    "contacts:contact-detail", kwargs={"contact_id": contact.pk}
                )
                return response
            return redirect(reverse("contacts:contact-detail", kwargs={"contact_id": contact.pk}))
        if request.htmx:
            return render(request, "contacts/partials/contact_form_modal.html", {
                "form": form,
                "contact": contact,
                "is_create": False,
            })
    else:
        form = ContactForm(instance=contact)

    if request.htmx:
        return render(request, "contacts/partials/contact_form_modal.html", {
            "form": form,
            "contact": contact,
            "is_create": False,
        })
    return render(request, "contacts/contact_form.html", {
        "form": form,
        "contact": contact,
        "is_create": False,
    })


def contact_archive(request, contact_id):
    """
    Acción de archivado. Solo POST.

    Éxito   →   HX-Redirect a contact-list.
    Error   →   partials/modal_error.html con mensaje de negocio.
                Target esperado: #modal-body
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        contact = get_contact_detail(contact_id)
    except Contact.DoesNotExist:
        raise Http404
    try:
        archive_contact(contact, actor=request.user)
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("contacts:contact-list")
        return response
    except ContactHasOpenDeals as e:
        return render(request, "partials/modal_error.html", {"error": str(e)})


def contact_restore(request, contact_id):
    """
    Acción de restauración. Solo POST.
    Usa all_objects — el contacto está soft-deleted.

    Éxito → HX-Redirect a contact-detail.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        contact = Contact.all_objects.get(pk=contact_id)
    except Contact.DoesNotExist:
        raise Http404
    restore_contact(contact, actor=request.user)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = reverse(
        "contacts:contact-detail", kwargs={"contact_id": contact_id}
    )
    return response


def contact_search(request):
    """
    Endpoint de búsqueda para comboboxes. Devuelve partial HTML.
    El parámetro `field` indica qué campo del formulario se está llenando
    (tenant / owner) para que el partial genere el método Alpine correcto.
    """
    q = request.GET.get("q", "").strip()
    field = request.GET.get("field", "tenant")
    if not q:
        return render(request, "contacts/partials/_search_results.html", {
            "results": [],
            "field": field,
        })
    return render(request, "contacts/partials/_search_results.html", {
        "results": get_contacts_for_search(q),
        "field": field,
    })