import json
from uuid import UUID

from datetime import date

from django.shortcuts import render
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.core.paginator import Paginator

from urllib.parse import urlencode

from .models import Property, PropertyMedia
from .services import (
    ALLOWED_MEDIA_MIME_TYPES,
    MAX_MEDIA_SIZE_BYTES,
    MAX_PHOTOS_PER_PROPERTY,
    MEDIA_MIME_EXTENSIONS,
    media_mime_type_from_key,
    upload_property_media,
    set_cover_media,
    delete_property_media,
    reorder_property_media,
)
from .selectors import (
    PropertyFilters, 
    get_property_list, 
    get_property_preview, 
    get_property_detail,
    get_properties_for_search,
    )
from .contexts import BadgeContext, PropertyListContext, MediaItemContext
from .exceptions import PropertyValidationError

from apps.billing.selectors import (
    get_rental_payment_status, 
    get_recent_documents_for_contract,
    get_billing_document_count_for_contract,
    )
from apps.billing.choices import PaymentStatus

from apps.common.storage import (
    get_public_media_url,
    generate_document_download_url,
    build_media_key,
    generate_media_upload_url,
    public_media_exists,
    delete_public_media,
)

from apps.contracts.selectors import get_active_contract_for_property

from apps.documents.selectors import get_document_list, DocumentFilters
from apps.documents.context import DocumentContext
from apps.documents.utils import categorize_document

from apps.listings.selectors import get_listings_for_property
from apps.listings.services import MIN_PHOTOS_TO_PUBLISH


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
            cover_url=get_public_media_url(prop.cover_media_list[0].r2_key)
            if prop.cover_media_list else None,
            display_price=next(
                (l.price for l in prop.price_listings if not op_type or l.operation_type == op_type),
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
    prop.cover_url = get_public_media_url(cover.r2_key) if cover else None

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
        doc.signed_url    = generate_document_download_url(doc.r2_key)
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
        cover_url = get_public_media_url(cover_media.r2_key)

    gallery_urls = [get_public_media_url(m.r2_key) for m in media_list]
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
            signed_url=generate_document_download_url(doc.r2_key),
            file_category=categorize_document(doc.content_type),
        )
        for doc in documents
    ]

    return render(request, "properties/partials/_detail_documents.html", {
        "documents": contexts,
    })


def property_search(request):
    """
    Endpoint de búsqueda para comboboxes. Devuelve partial HTML.
    Incluye owner_contact para auto-fill en formulario de contratos.
    """
    q = request.GET.get("q", "").strip()
    if not q:
        return render(request, "properties/partials/_search_results.html", {
            "results": [],
        })
    return render(request, "properties/partials/_search_results.html", {
        "results": get_properties_for_search(q),
    })


def media_sign(request, pk):
    """
    Firma una subida de foto (§9): re-valida MIME/tamaño/techo declarados
    por el browser, construye la key y devuelve {key, url} para el PUT
    directo a R2.

    Primer endpoint JSON del backoffice: la subida es un flujo AJAX (fetch),
    no una navegación HTMX, así que devuelve datos estructurados y el
    frontend es dueño de presentar el error por archivo. Ver ADR de frontend.

    La extensión de la key la deriva el server del MIME validado, no del
    filename del cliente: la key siempre refleja el archivo final (§7).
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Cuerpo inválido."}, status=400)

    content_type = payload.get("content_type")
    size = payload.get("size")

    if content_type not in ALLOWED_MEDIA_MIME_TYPES:
        return JsonResponse(
            {"error": "Formato no permitido. Usá JPG, PNG o WebP."},
            status=400,
        )
    if not isinstance(size, int) or size <= 0 or size > MAX_MEDIA_SIZE_BYTES:
        return JsonResponse(
            {"error": "La foto supera el máximo de 10 MB."},
            status=400,
        )
    if property.media.count() >= MAX_PHOTOS_PER_PROPERTY:
        return JsonResponse(
            {"error": f"Llegaste al máximo de {MAX_PHOTOS_PER_PROPERTY} fotos."},
            status=409,
        )

    key = build_media_key(
        property_id=property.pk,
        filename=f"upload{MEDIA_MIME_EXTENSIONS[content_type]}",
    )
    url = generate_media_upload_url(key=key, content_type=content_type)
    return JsonResponse({"key": key, "url": url})


def _gate_context(property):
    return {
        "photo_count": property.media.count(),
        "min_photos": MIN_PHOTOS_TO_PUBLISH,
        "max_photos": MAX_PHOTOS_PER_PROPERTY,
    }


def _media_item_context(media):
    return MediaItemContext(
        id=media.id,
        url=get_public_media_url(media.r2_key),
        is_cover=media.is_cover,
        order=media.order,
    )


def _media_confirm_response(request, property, media):
    return render(request, "properties/partials/_media_confirm_response.html", {
        "item": _media_item_context(media),
        **_gate_context(property),
    })


def _media_gallery_response(request, property):
    return render(request, "properties/partials/_media_gallery.html", {
        "media_items": [_media_item_context(m) for m in property.media.all()],
        **_gate_context(property),
    })


def media_confirm(request, pk):
    """
    Confirma una subida (§9): verifica que el objeto llegó a R2
    (public_media_exists, §10.2) antes de registrar PropertyMedia, y
    devuelve el card de la foto (beforeend a la galería) + el contador de
    gate por OOB swap.

    Éxito → HTML (presentación de estado persistido). Fallo → JSON (dato
    para que el cliente marque la foto fallida y ofrezca reintento). Ver
    criterio del ADR de frontend.

    El mime lo deriva de la extensión de la key (que el server generó en
    sign). La key se valida contra el prefijo de la propiedad: nunca se
    registra acá un objeto de otra propiedad.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Cuerpo inválido."}, status=400)

    key = payload.get("key") or ""
    mime_type = media_mime_type_from_key(key)

    if not key.startswith(f"properties/{property.pk}/") or mime_type is None:
        return JsonResponse({"error": "Key inválida."}, status=400)

    existing = PropertyMedia.objects.filter(r2_key=key).first()
    if existing is not None:
        return _media_confirm_response(request, property, existing)

    if property.media.count() >= MAX_PHOTOS_PER_PROPERTY:
        return JsonResponse(
            {"error": f"Llegaste al máximo de {MAX_PHOTOS_PER_PROPERTY} fotos."},
            status=409,
        )

    if not public_media_exists(key):
        return JsonResponse(
            {"error": "La foto no llegó a subirse. Reintentá."},
            status=422,
        )

    media = upload_property_media(
        property=property,
        r2_key=key,
        mime_type=mime_type,
        order=property.media.count(),
        actor=request.user,
    )
    return _media_confirm_response(request, property, media)


def media_set_cover(request, id):
    """
    Marca una foto como portada (§9). set_cover_media es atómico (§10):
    apaga la portada previa y prende esta. Devuelve la galería re-renderizada
    con la verdad nueva — el frontend no calcula la posición del badge.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        media = PropertyMedia.objects.select_related("property").get(pk=id)
    except PropertyMedia.DoesNotExist:
        raise Http404
    set_cover_media(media=media)
    return _media_gallery_response(request, media.property)


def media_delete(request, id):
    """
    Borra una foto (§9): R2 primero (delete_public_media lanza si falla, así
    la fila de DB nunca queda huérfana), DB después (delete_property_media con
    promoción de portada, §10.4). Devuelve la galería re-renderizada: si se
    borró la portada, ya trae la promovida — el frontend no decide nada.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        media = PropertyMedia.objects.select_related("property").get(pk=id)
    except PropertyMedia.DoesNotExist:
        raise Http404
    property = media.property
    delete_public_media(media.r2_key)
    delete_property_media(media=media)
    return _media_gallery_response(request, property)


def media_reorder(request, pk):
    """
    Reordena las fotos de una propiedad (§9). reorder_property_media (§10.3)
    exige que el set de ids coincida exacto.

    Éxito → 204 (HTMX no swapea: el cliente ya impuso el orden, no hay verdad
    nueva que renderizar). Set desincronizado (borrado concurrente / DOM
    viejo) → 200 + galería re-renderizada: re-sync a la verdad de DB. No hay
    modal abierto en un drag, así que el re-render ES la recuperación —
    no va por modal_error. Body malformado → 400 JSON.

    Contrato del body: {"ordered_ids": [<uuid>, ...]}.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404

    try:
        payload = json.loads(request.body)
        raw_ids = payload["ordered_ids"]
        if not isinstance(raw_ids, list):
            raise ValueError
        ordered_ids = [UUID(str(x)) for x in raw_ids]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return JsonResponse({"error": "Orden inválido."}, status=400)

    try:
        reorder_property_media(
            property=property,
            ordered_media_ids=ordered_ids,
            actor=request.user,
        )
    except PropertyValidationError:
        return _media_gallery_response(request, property)

    return HttpResponse(status=204)


def property_edit(request, pk):
    """
    Página de edición de una propiedad (§2, parcial). S3a monta la sección
    de fotos; el form escalar de edición es un hueco nombrado hasta el punto 6.
    """
    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404
    return render(request, "properties/property_edit.html", {
        "property": property,
        "media_items": [_media_item_context(m) for m in property.media.all()],
        **_gate_context(property),
    })