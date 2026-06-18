import json

from django.shortcuts import render
from django.http import Http404

from .models import Property
from .selectors import PropertyFilters, get_property_list, get_property_preview, get_property_detail
from .contexts import PropertyListContext

from apps.listings.selectors import get_listings_for_property

from apps.documents.selectors import get_document_list, DocumentFilters
from apps.documents.context import DocumentContext
from apps.documents.utils import categorize_document

from apps.common.storage import build_media_url, generate_document_url

def property_list(request):
    tab = request.GET.get("tab", "all")
    op_type = {"rent": "rent", "sale": "sale"}.get(tab)  # None si tab == "all"

    filters = PropertyFilters(
        status=[request.GET.get("status")] if request.GET.get("status") not in (None, "all") else None,
        operation_type=op_type,
    )

    properties = list(get_property_list(filters))

    property_contexts = [
        PropertyListContext(
            property=prop,
            cover_url=build_media_url(prop.cover_media_list[0].r2_key)
            if prop.cover_media_list else None,
            display_price=next(
                (l.price for l in prop.active_listings if not op_type or l.operation_type == op_type),
                None,
            ),
        )
        for prop in properties
    ]

    return render(request, "properties/property_list.html", {
        "properties": property_contexts,
        "total_count": len(properties),
        "current_tab": tab,
        "current_status": request.GET.get("status", "all"),
        "search_query": request.GET.get("q", ""),
        "page_obj": None,      # placeholder — se activa con paginación
        "next_page_url": None,
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
    return render(request, "properties/partials/_slide_over_billing.html", {
        "property": prop,
    })


def slide_over_contacts(request, pk):
    try:
        prop = get_property_detail(pk)
    except Property.DoesNotExist:
        raise Http404
    return render(request, "properties/partials/_slide_over_contacts.html", {
        "property": prop,
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

    media_list = list(prop.media.all())  # ya viene prefetched ordenado
    cover_url = None
    if media_list:
        cover_media = next((m for m in media_list if m.is_cover), media_list[0])
        cover_url = build_media_url(cover_media.r2_key)

    gallery_urls = [build_media_url(m.r2_key) for m in media_list]
    listings = list(get_listings_for_property(pk))

    return render(request, "properties/property_detail.html", {
        "property": prop,
        "cover_url": cover_url,
        "gallery_urls": gallery_urls,
        "gallery_urls_json": json.dumps(gallery_urls),
        "listings": listings,
    })


def detail_publications(request, pk):
    if not Property.objects.filter(pk=pk).exists():
        raise Http404
    listings = list(get_listings_for_property(pk))
    return render(request, "properties/partials/_detail_publications.html", {
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