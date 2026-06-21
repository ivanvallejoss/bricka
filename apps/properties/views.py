import json

from datetime import date

from django.shortcuts import render
from django.http import Http404
from django.core.paginator import Paginator

from urllib.parse import urlencode

from .models import Property
from .selectors import PropertyFilters, get_property_list, get_property_preview, get_property_detail
from .contexts import BadgeContext, PropertyListContext

from apps.billing.selectors import (
    get_rental_payment_status, 
    get_recent_documents_for_contract,
    get_billing_document_count_for_contract,
    )
from apps.billing.choices import PaymentStatus

from apps.common.storage import build_media_url, generate_document_url

from apps.contracts.selectors import get_active_contract_for_property

from apps.documents.selectors import get_document_list, DocumentFilters
from apps.documents.context import DocumentContext
from apps.documents.utils import categorize_document

from apps.listings.selectors import get_listings_for_property


_BADGE_MAP = {
    PaymentStatus.PAID:    BadgeContext(text="Pago",      style="success"),
    PaymentStatus.PENDING: BadgeContext(text="Pendiente", style="warning"),
    PaymentStatus.OVERDUE: BadgeContext(text="En mora",   style="danger"),
}


def property_list(request):
    tab = request.GET.get("tab", "all")
    op_type = {"rent": "rent", "sale": "sale"}.get(tab)
    search = request.GET.get("q", "").strip() or None
    status_param = request.GET.get("status")

    filters = PropertyFilters(
        status=[status_param] if status_param not in (None, "all") else None,
        operation_type=op_type,
        search=search,
    )

    qs = get_property_list(filters)
    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    all_contracts = [c for prop in page_obj.object_list for c in prop.active_contracts_list]
    payment_statuses = get_rental_payment_status(all_contracts, as_of=date.today())

    prop_badges = {
        c.property_id: _BADGE_MAP[payment_statuses[c.id]]
        for c in all_contracts
        if payment_statuses.get(c.id) in _BADGE_MAP
    }

    property_contexts = [
        PropertyListContext(
            property=prop,
            cover_url=build_media_url(prop.cover_media_list[0].r2_key)
            if prop.cover_media_list else None,
            display_price=next(
                (l.price for l in prop.active_listings if not op_type or l.operation_type == op_type),
                None,
            ),
            contextual_badge=prop_badges.get(prop.id),
        )
        for prop in page_obj.object_list
    ]

    if page_obj.has_next():
        params = {
            "tab": tab,
            "status": request.GET.get("status", "all"),
            "q": request.GET.get("q", ""),
            "page": page_obj.next_page_number(),
        }
        next_page_url = f"{request.path}?{urlencode(params)}"
    else:
        next_page_url = None

    if request.htmx:
        return render(request, "properties/partials/_property_rows.html", {
            "properties": property_contexts,
            "total_count": paginator.count,
            "page_obj": page_obj,
            "next_page_url": next_page_url,
        })

    return render(request, "properties/property_list.html", {
        "properties": property_contexts,
        "total_count": paginator.count,
        "current_tab": tab,
        "current_status": request.GET.get("status", "all"),
        "search_query": request.GET.get("q", ""),
        "page_obj": page_obj,
        "next_page_url": next_page_url,
    })


def property_slide_over(request, pk):
    try:
        prop = get_property_preview(pk)
    except Property.DoesNotExist:
        raise Http404

    cover = prop.cover_media_list[0] if prop.cover_media_list else None
    prop.cover_url = build_media_url(cover.r2_key) if cover else None

    listings = list(get_listings_for_property(pk))

    return render(request, "properties/partials/_slide_over.html", {
        "property": prop,
        "listings": listings,
    })


def slide_over_publications(request, pk):
    try:
        prop = get_property_preview(pk)
    except Property.DoesNotExist:
        raise Http404
    listings = list(get_listings_for_property(pk))
    return render(request, "properties/partials/_slide_over_publications.html", {
        "property": prop,
        "listings": listings,
    })


def slide_over_billing(request, pk):
    try:
        prop = get_property_preview(pk)
    except Property.DoesNotExist:
        raise Http404

    contract = get_active_contract_for_property(pk)
    payment_status = None
    recent_documents = []

    if contract:
        statuses = get_rental_payment_status([contract], as_of=date.today())
        payment_status = statuses.get(contract.id)
        recent_documents = list(get_recent_documents_for_contract(contract.id))

    return render(request, "properties/partials/_slide_over_billing.html", {
        "property": prop,
        "contract": contract,
        "payment_status": payment_status,
        "recent_documents": recent_documents,
    })


def slide_over_contacts(request, pk):
    try:
        prop = get_property_detail(pk)
    except Property.DoesNotExist:
        raise Http404

    active_contract = get_active_contract_for_property(pk)
    
    return render(request, "properties/partials/_slide_over_contacts.html", {
        "property": prop,
        "active_contract": active_contract,
    })


def slide_over_documents(request, pk):
    try:
        prop = get_property_preview(pk)
    except Property.DoesNotExist:
        raise Http404

    documents = list(get_document_list(DocumentFilters(property_id=pk)))
    for doc in documents:
        doc.signed_url    = generate_document_url(doc.r2_key)
        doc.file_category = categorize_document(doc.content_type)

    return render(request, "properties/partials/_slide_over_documents.html", {
        "property": prop,
        "documents": documents,
    })


def property_detail(request, pk):
    try:
        prop = get_property_detail(pk)
    except Property.DoesNotExist:
        raise Http404

    active_contract = get_active_contract_for_property(pk)
    payment_status = None
    invoice_count = 0
    recent_documents = []

    if active_contract:
        statuses = get_rental_payment_status([active_contract], as_of=date.today())
        payment_status = statuses.get(active_contract.id)
        invoice_count = get_billing_document_count_for_contract(active_contract.id)
        recent_documents = list(get_recent_documents_for_contract(active_contract.id, limit=6))
    
    document_count = get_document_list(DocumentFilters(property_id=pk)).count()

    media_list = list(prop.media.all())  # ya viene prefetched ordenado
    cover_url = None
    if media_list:
        cover_media = next((m for m in media_list if m.is_cover), media_list[0])
        cover_url = build_media_url(cover_media.r2_key)

    gallery_urls = [build_media_url(m.r2_key) for m in media_list]
    listings = list(get_listings_for_property(pk))

    return render(request, "properties/property_detail.html", {
        "property": prop,
        "active_contract": active_contract,
        "payment_status": payment_status,
        "invoice_count": invoice_count,
        "document_count": document_count,
        "recent_documents": recent_documents,
        "cover_url": cover_url,
        "gallery_urls": gallery_urls,
        "gallery_urls_json": json.dumps(gallery_urls),
        "listings": listings,
    })


def detail_publication(request, pk):
    if not Property.objects.filter(pk=pk).exists():
        raise Http404
    listings = list(get_listings_for_property(pk))
    return render(request, "properties/partials/_detail_publication.html", {
        "listings": listings,
    })


def detail_documents(request, pk):
    if not Property.objects.filter(pk=pk).exists():
        raise Http404

    documents = get_document_list(DocumentFilters(property_id=pk))

    contexts = [
        DocumentContext(
            document=doc,
            signed_url=generate_document_url(doc.r2_key),
            file_category=categorize_document(doc.content_type),
        )
        for doc in documents
    ]

    return render(request, "properties/partials/_detail_documents.html", {
        "documents": contexts,
    })
