import json
from uuid import UUID

from datetime import date

from django.shortcuts import render, redirect
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.core.paginator import Paginator
from django.core.exceptions import ObjectDoesNotExist
from django.contrib import messages
from django.contrib.gis.geos import Point
from django.conf import settings
from django.urls import reverse

from urllib.parse import urlencode

from .models import Property, PropertyMedia, Feature
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
    update_property,
    create_property,
    update_external_source,
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
from .forms import (
    PropertyForm, 
    PropertyCreateForm, 
    ListingCreateForm, 
    ListingPriceForm, 
    ExternalSourceForm,
    LocationForm,
    )
from .choices import FeatureCategory, PropertyType, PropertyStatus
from .checklist import FLOW_EDIT, FLOW_WIZARD, build_publication_checklist

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
from apps.common.geocoding import geocode_address, GeocodeUnavailable

from apps.contacts.models import Contact

from apps.contracts.selectors import get_active_contract_for_property

from apps.documents.selectors import get_document_list, DocumentFilters
from apps.documents.context import DocumentContext
from apps.documents.utils import categorize_document

from apps.listings.selectors import get_listings_for_property, get_listing_detail
from apps.listings.services import (
    MIN_PHOTOS_TO_PUBLISH, MIN_DESCRIPTION_LENGTH,
    create_listing, 
    update_listing_status, 
    update_listing_price,
    archive_listing,
)
from apps.listings.exceptions import ListingValidationError, ListingPublicationRequirementsError
from apps.listings.choices import OperationType, PricePeriod, ListingStatus

from apps.operations.services import withdraw_property, restore_property
from apps.operations.exceptions import InvalidPropertyTransition


_BADGE_MAP = {
    PaymentStatus.PAID:    BadgeContext(text="Pago",      style="success"),
    PaymentStatus.PENDING: BadgeContext(text="Pendiente", style="warning"),
    PaymentStatus.OVERDUE: BadgeContext(text="En mora",   style="danger"),
}

WIZARD_STEPS = [(1, "Identificación"), (2, "Detalle"), (3, "Fotos"), (4, "Operación")]

# Resolución del gap de period (enmienda S3b): el form de alta expone
# venta/alquiler; period se deriva de operation_type. Espeja lo que el seed ya
# asume. temporary_rent no se expone en V1, así que no entra al mapa.
OPERATION_PERIOD = {
    OperationType.SALE: PricePeriod.TOTAL,
    OperationType.RENT: PricePeriod.MONTHLY,
}


def property_new(request):
    """
    Fase 1 del wizard (§1): identificación. POST crea el borrador vía
    create_property y salta a la fase siguiente. is_external es acá o nunca
    (prohibido en update_property). La regla is_external → agency la valida
    create_property (PropertyValidationError) y se muestra como non-field
    error, sin adivinar el campo desde el mensaje genérico.
    """
    if request.method == "POST":
        form = PropertyCreateForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                property = create_property(
                    property_type=cd["property_type"],
                    address_line=cd["address_line"],
                    city=cd["city"],
                    province=cd["province"],
                    neighborhood=cd["neighborhood"],
                    is_external=cd["is_external"],
                    agency_name=cd["agency_name"],
                    actor=request.user,
                )
            except PropertyValidationError as e:
                form.add_error(None, str(e))
            else:
                return redirect("properties:new_detalle", pk=property.pk)
    else:
        form = PropertyCreateForm()

    return render(request, "properties/property_new.html", {
        "form": form,
        "property_types": PropertyType.choices,
        "wizard_steps": WIZARD_STEPS,
        "current_step": 1,
    })


def property_new_detalle(request, pk):
    """
    Fase 2 del wizard (§1): detalle. Reusa el form escalar (§5) + bloque externas
    si is_external (§6). Location (§4) pendiente. Ambos submits guardan:
    "Guardar y salir" → detail; "Siguiente" → fotos.
    """
    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404

    if request.method == "POST":
        form = PropertyForm(request.POST, instance=property)
        if form.is_valid():
            _save_property_scalar(property, form, request)
            if request.POST.get("action") == "next":
                return redirect("properties:new_fotos", pk=property.pk)
            return redirect("properties:detail", pk=property.pk)
    else:
        form = PropertyForm(instance=property)

    selected_slugs, owner_initial = _selected_and_owner(request, property, form)
    return render(request, "properties/property_new_detalle.html", {
        "property": property,
        "form": form,
        "feature_groups": _feature_groups(),
        "selected_slugs": selected_slugs,
        "owner_initial": owner_initial,
        "min_description": MIN_DESCRIPTION_LENGTH,
        "wizard_steps": WIZARD_STEPS,
        "current_step": 2,
        **_externas_section_context(property),
        **_location_section_context(property),
    })


def property_new_fotos(request, pk):
    """
    Fase 3 del wizard (§1): fotos. Reusa la sección de media entera (galería +
    uploader). Las fotos persisten al subirse (acción inmediata), así que no
    hay submit acá: "Atrás" → detalle, "Finalizar" → detail son navegación.
    """
    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404
    return render(request, "properties/property_new_fotos.html", {
        "property": property,
        "media_items": [_media_item_context(m) for m in property.media.all()],
        **_gate_context(property),
        "wizard_steps": WIZARD_STEPS,
        "current_step": 3,
    })


def property_new_operacion(request, pk):
    """
    Fase 4 del wizard (§1, §8-listing): operación. Opcional. Reusa la sección de
    operación entera con FLOW_WIZARD, así los deep links del checklist (si se
    publica y el gate rechaza) apuntan a las fases del wizard, no a las anclas de
    edición. La sección persiste por HTMX (create/publish/price); acá no hay
    submit: "Atrás" → fotos, "Finalizar" → detail son navegación.
    """
    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404
    return render(request, "properties/property_new_operacion.html", {
        **_operacion_section_context(property, FLOW_WIZARD),
        "wizard_steps": WIZARD_STEPS,
        "current_step": 4,
    })


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
    listings = _annotate_listing_badges(prop, list(get_listings_for_property(pk)))
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


def _annotate_listing_badges(prop, listings):
    """
    Badge contextual por listing (S4/§8), resuelto en view — patrón BadgeContext.
    Caso único hoy: alquiler PAUSED post-venta. Sin joins nuevos: ambos estados
    ya están en memoria, la nota contextual entra gratis (cláusula de §8).
    PAUSED por retiro (UNAVAILABLE) NO lleva badge.
    """
    for listing in listings:
        listing.contextual_badge = None
        if (
            listing.status == ListingStatus.PAUSED
            and prop.status == PropertyStatus.SOLD
            and listing.operation_type in (OperationType.RENT, OperationType.TEMPORARY_RENT)
        ):
            listing.contextual_badge = BadgeContext(text="Pausada", style="warning")
    return listings


def _property_detail_context(pk):
    """
    Contexto completo del detail. Lo comparten property_detail (GET) y
    property_restore (render directo en rechazo del gate). Lanza
    Property.DoesNotExist — el caller decide el 404.
    Convención S3b: devuelve TODO lo que property_detail.html referencia.
    """
    prop = get_property_detail(pk)

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
    listings = _annotate_listing_badges(prop, list(get_listings_for_property(pk)))

    return {
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
    }


def property_detail(request, pk):
    try:
        context = _property_detail_context(pk)
    except Property.DoesNotExist:
        raise Http404
    return render(request, "properties/property_detail.html", context)


def property_withdraw(request, pk):
    """
    Retira la propiedad del mercado (§8): AVAILABLE → UNAVAILABLE vía el
    orquestador (withdraw_property pausa los listings publicados — retienen
    slot, salen de la landing). Form nativo POST + redirect (convención de
    destructivas: el sidebar renderiza dos veces). InvalidPropertyTransition
    solo es alcanzable por página vieja o carrera (el botón no existe en
    estados inválidos) → messages.error + redirect, no modal (enmienda S4).
"""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        prop = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404
    try:
        withdraw_property(property=prop, actor=request.user)
    except InvalidPropertyTransition as e:
        messages.error(request, str(e))
    return redirect("properties:detail", pk=pk)


def property_restore(request, pk):
    """
    Reactiva la propiedad (§8): UNAVAILABLE → AVAILABLE. restore_property
    despausa vía update_listing_status(PUBLISHED) → el gate corre adentro;
    su rechazo propaga y el atomic del orquestador revierte TODO (A1).
    Rechazo → render directo del detail con el checklist compartido
    (flow=edit), releyendo estado post-rollback desde DB. Sin modal:
    transporte nativo (enmienda S4).
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        prop = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404
    try:
        restore_property(property=prop, actor=request.user)
    except InvalidPropertyTransition as e:
        messages.error(request, str(e))
    except ListingPublicationRequirementsError as e:
        context = _property_detail_context(pk)
        context["checklist_items"] = build_publication_checklist(
            context["property"], e.missing, FLOW_EDIT
        )
        return render(request, "properties/property_detail.html", context)
    return redirect("properties:detail", pk=pk)


def detail_publication(request, pk):
    try:
        prop = get_property_preview(pk)
    except Property.DoesNotExist:
        raise Http404
    listings = _annotate_listing_badges(prop, list(get_listings_for_property(pk)))
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


def _operacion_section_context(property, flow, listing_form=None):
    listings = list(get_listings_for_property(property.pk))
    # Capa UX durable contra drafts duplicados: no ofrecer un tipo que ya tiene
    # un listing no-cerrado. NO es la garantía — esa es la constraint + el chequeo
    # del service (ventana de unicidad). Acá solo se evita ofrecer lo que fallaría.
    # closed no bloquea (permite re-listar tras un cierre).
    taken = {l.operation_type for l in listings if l.status != ListingStatus.CLOSED}
    available_operations = [
        (op.value, op.label)
        for op in (OperationType.SALE, OperationType.RENT)
        if op.value not in taken
    ]
    return {
        "property": property,
        "listings": listings,
        "listing_form": listing_form if listing_form is not None else ListingCreateForm(),
        "flow": flow,
        "available_operations": available_operations,
    }


def _externas_section_context(property, external_form=None, saved=False):
    if not property.is_external:
        return {}
    source = property.external_source
    if external_form is None:
        external_form = ExternalSourceForm(initial={
            "agency_name": source.agency_name,
            "source_url": source.source_url,
            "agreed_commission_percent": source.agreed_commission_percent,
        })
    return {
        "property": property,
        "external_form": external_form,
        "externas_saved": saved,
    }


def _location_section_context(property):
    center = settings.GEO_CITY_CENTERS.get(property.city, settings.GEO_DEFAULT_CENTER)
    existing = None
    if property.location:
        existing = [property.location.y, property.location.x]  # [lat, lng]
        center = existing
    address_query = ", ".join(
        p for p in [property.address_line, property.city, property.province] if p
    )
    return {
        "property": property,
        "map_center_json": json.dumps(list(center)),
        "existing_location_json": json.dumps(existing),
        "address_query": address_query,
    }


def _listing_row_context(listing, flow, price_error=None):
    return {"listing": listing, "flow": flow, "price_error": price_error}


def _modal_response(request, modal_template, extra_context):
    """Devuelve un modal re-dirigiendo el swap a #modal-container (HX-Retarget).
    Para acciones cuyo éxito re-renderea inline pero cuyo error/rechazo va al
    modal — el partial de contenido (checklist / modal_error) viaja como body."""
    response = render(request, "partials/_modal_shell.html", {
        "modal_template": modal_template,
        **extra_context,
    })
    response["HX-Retarget"] = "#modal-container"
    response["HX-Reswap"] = "innerHTML"
    return response


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


def _feature_groups():
    return [
        {"label": label, "features": Feature.objects.filter(category=value, is_active=True)}
        for value, label in FeatureCategory.choices
    ]


def _owner_initial(property, submitted_owner_id):
    # Estado inicial del combobox de owner. GET: owner actual. Error: el owner
    # submitted (ya validado como UUID) para no perder la selección al re-render.
    if submitted_owner_id:
        contact = Contact.objects.filter(pk=submitted_owner_id).first()
    else:
        contact = property.owner_contact
    if contact is None:
        return {"id": "", "text": ""}
    return {"id": str(contact.pk), "text": contact.full_name}


def _save_property_scalar(property, form, request):
    """
    Escritura escalar compartida por edición y wizard-fase-2. KWARGS
    EXPLÍCITOS, nunca **cleaned_data: location y externas quedan UNSET a
    propósito (S3b); un guardado no las borra. features y owner_contact_id
    viajan (reemplazo). Una sola fuente de esta disciplina — las dos puertas
    no pueden divergir.
    """
    cd = form.cleaned_data
    update_property(
        property=property,
        title=cd["title"],
        description=cd["description"],
        address_line=cd["address_line"],
        city=cd["city"],
        province=cd["province"],
        neighborhood=cd["neighborhood"],
        area_m2=cd["area_m2"],
        bedrooms=cd["bedrooms"],
        bathrooms=cd["bathrooms"],
        parking_spaces=cd["parking_spaces"],
        year_built=cd["year_built"],
        youtube_video_url=cd["youtube_video_url"],
        features=request.POST.getlist("features"),
        owner_contact_id=cd["owner_contact_id"],
        actor=request.user,
    )


def _selected_and_owner(request, property, form):
    # selected_slugs + owner_initial: GET usa lo persistido, POST-error lo
    # submitted (para no perder ticks ni la selección de owner al re-render).
    if request.method == "POST":
        return (
            set(request.POST.getlist("features")),
            _owner_initial(property, form.cleaned_data.get("owner_contact_id")),
        )
    return (
        set(property.features.values_list("slug", flat=True)),
        _owner_initial(property, None),
    )


def property_edit(request, pk):
    """
    Página de edición (§2). GET renderiza el form escalar + la sección de
    fotos. POST guarda vía update_property (helper compartido) y vuelve al
    detail. location y externas quedan UNSET (S3b).
    """
    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404

    if request.method == "POST":
        form = PropertyForm(request.POST, instance=property)
        if form.is_valid():
            _save_property_scalar(property, form, request)
            messages.success(request, "Cambios guardados.")
            return redirect("properties:detail", pk=property.pk)
    else:
        form = PropertyForm(instance=property)

    selected_slugs, owner_initial = _selected_and_owner(request, property, form)
    context = {
        "property": property,
        "form": form,
        "feature_groups": _feature_groups(),
        "selected_slugs": selected_slugs,
        "owner_initial": owner_initial,
        "media_items": [_media_item_context(m) for m in property.media.all()],
        **_gate_context(property),
        "min_description": MIN_DESCRIPTION_LENGTH,
        **_operacion_section_context(property, FLOW_EDIT),
        **_externas_section_context(property),
        **_location_section_context(property),
    }
    return render(request, "properties/property_edit.html", context)


def listing_create(request, pk):
    """
    Alta de listing (§8-listing, §9). POST-only. El form de la sección Operación
    postea acá; la respuesta re-renderea la sección entera (lista + form fresco).
    period se deriva de operation_type. La unicidad (create_listing choca contra
    un activo del tipo) solo la dispara una carrera → error inline en el form; la
    sección re-renderizada ya muestra ese activo. flow viaja para que la vertical
    publicación arme los deep links del checklist.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404

    flow = request.POST.get("flow", FLOW_EDIT)
    form = ListingCreateForm(request.POST)

    if form.is_valid():
        operation_type = form.cleaned_data["operation_type"]
        try:
            create_listing(
                property=property,
                operation_type=operation_type,
                price=form.cleaned_data["price"],
                currency=form.cleaned_data["currency"],
                period=OPERATION_PERIOD[operation_type],
                price_min_acceptable=form.cleaned_data["price_min_acceptable"],
                actor=request.user,
            )
        except ListingValidationError as e:
            form.add_error(None, str(e))
        else:
            form = None  # éxito → form fresco en la sección re-renderizada

    return render(
        request,
        "properties/partials/_operacion_section.html",
        _operacion_section_context(property, flow, form),
    )


def external_source_update(request, pk):
    """
    Corrige la fuente externa de una propiedad (§6, §10.5). POST-only. El bloque
    solo existe si is_external, así que un POST a una no-externa es 404 (el
    recurso no existe, no es error de negocio). agency_name requerido lo valida
    el form; el service es el backstop de dominio. Éxito → re-renderea el bloque
    con los valores actualizados y "Guardado".
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404
    if not property.is_external:
        raise Http404

    form = ExternalSourceForm(request.POST)
    saved = False
    if form.is_valid():
        update_external_source(
            property=property,
            agency_name=form.cleaned_data["agency_name"],
            source_url=form.cleaned_data["source_url"],
            agreed_commission_percent=form.cleaned_data["agreed_commission_percent"],
            actor=request.user,
        )
        form = None
        saved = True

    return render(
        request,
        "properties/partials/_externas_section.html",
        _externas_section_context(property, form, saved),
    )


def listing_publish(request, pk, listing_id):
    """
    Publica un listing (§8-listing, §9). POST-only. Éxito → re-renderea la fila
    (ya PUBLISHED, sin botón publicar). Rechazo del gate → checklist en modal;
    unicidad → modal_error en modal (ambos vía HX-Retarget). except en orden
    hija-primero: ListingPublicationRequirementsError antes de ListingValidationError.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        listing = get_listing_detail(listing_id)
    except ObjectDoesNotExist:
        raise Http404
    if listing.property_id != pk:
        raise Http404

    flow = request.POST.get("flow", FLOW_EDIT)
    try:
        update_listing_status(
            listing=listing, status=ListingStatus.PUBLISHED, actor=request.user,
        )
    except ListingPublicationRequirementsError as e:
        return _modal_response(request, "properties/partials/_publication_checklist.html", {
            "checklist_items": build_publication_checklist(listing.property, e.missing, flow),
        })
    except ListingValidationError as e:
        return _modal_response(request, "partials/modal_error.html", {"error": str(e)})

    return render(
        request,
        "properties/partials/_operacion_listing_row.html",
        _listing_row_context(listing, flow),
    )


def listing_price(request, pk, listing_id):
    """
    Cambia el precio de un listing (§8-listing, §9). POST-only. Éxito y error de
    validación re-renderean la misma fila (un solo target). El historial lo
    escribe update_listing_price.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        listing = get_listing_detail(listing_id)
    except ObjectDoesNotExist:
        raise Http404
    if listing.property_id != pk:
        raise Http404

    flow = request.POST.get("flow", FLOW_EDIT)
    form = ListingPriceForm(request.POST)
    if form.is_valid():
        listing = update_listing_price(
            listing=listing, price=form.cleaned_data["price"], actor=request.user,
        )
        return render(
            request,
            "properties/partials/_operacion_listing_row.html",
            _listing_row_context(listing, flow),
        )

    return render(
        request,
        "properties/partials/_operacion_listing_row.html",
        _listing_row_context(listing, flow, price_error=form.errors["price"][0]),
    )


def listing_pause(request, pk, listing_id):
    """
    Saca un listing de publicaciones (insumo S3b): PUBLISHED -> PAUSED.
    Flip liviano de listing, SIN orquestador — la capa propiedad no se toca.
    Guard de estado en la view: update_listing_status no valida transiciones
    hacia PAUSED, y el boton solo existe en PUBLISHED — un POST desde otra
    fila es staleness/carrera -> modal_error.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        listing = get_listing_detail(listing_id)
    except ObjectDoesNotExist:
        raise Http404
    if listing.property_id != pk:
        raise Http404

    flow = request.POST.get("flow", FLOW_EDIT)
    if listing.status != ListingStatus.PUBLISHED:
        return _modal_response(request, "partials/modal_error.html", {
            "error": "Solo se puede sacar de publicaciones un listing publicado.",
        })
    listing = update_listing_status(
        listing=listing, status=ListingStatus.PAUSED, actor=request.user,
    )
    return render(
        request,
        "properties/partials/_operacion_listing_row.html",
        _listing_row_context(listing, flow),
    )


def listing_discard(request, pk, listing_id):
    """
    Descarta un listing DRAFT (insumo S3b): archive_listing (soft-delete).
    Libera el slot de la constraint -> recrear el tipo queda permitido. Es la
    via de salida del DRAFT pegado (friccion de S3b). Accion destructiva ->
    form nativo + redirect (convencion frontend.md); el destino depende del
    flujo. Solo DRAFT es descartable: para otros estados la accion no existe
    (mismo criterio que el boton) -> 404.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        listing = get_listing_detail(listing_id)
    except ObjectDoesNotExist:
        raise Http404
    if listing.property_id != pk:
        raise Http404
    if listing.status != ListingStatus.DRAFT:
        raise Http404

    archive_listing(listing=listing, actor=request.user)

    flow = request.POST.get("flow", FLOW_EDIT)
    if flow == FLOW_WIZARD:
        return redirect("properties:new_operacion", pk=pk)
    return redirect(reverse("properties:edit", args=[pk]) + "#operacion-section")


def geocode(request):
    """
    Proxy de geocoding (§4). GET ?q=<dirección>. Vive bajo /backoffice/ → detrás
    del middleware de S8; nunca abierto a internet (un proxy sin auth quema la
    cuota de Nominatim y la IP ante su ban). Schema uniforme {available, result}:
      - {"available": true,  "result": {lat, lon, display_name}}  → match.
      - {"available": true,  "result": null}                       → sin resultado.
      - {"available": false, "result": null}                       → no disponible
        (timeout, red, o rate-gate). El frontend cae a centro default + pin manual.
    """
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse({"available": True, "result": None})
    try:
        result = geocode_address(query)
    except GeocodeUnavailable:
        return JsonResponse({"available": False, "result": None})
    if result is None:
        return JsonResponse({"available": True, "result": None})
    return JsonResponse({"available": True, "result": {
        "lat": result.lat,
        "lon": result.lon,
        "display_name": result.display_name,
    }})


def location_update(request, pk):
    """
    Persiste la ubicación de una propiedad (§4, §9). POST-only, lat/lng. Arma el
    Point (footgun: Point(x=longitud, y=latitud)) y persiste vía update_property
    — location queda aislado por UNSET, el form escalar nunca lo pisa. Devuelve
    JSON: el mapa es un Leaflet vivo, re-renderear el bloque lo destruiría, así
    que el JS actualiza el estado con la respuesta en vez de swappear.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        property = Property.objects.get(pk=pk)
    except Property.DoesNotExist:
        raise Http404

    form = LocationForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"saved": False, "errors": form.errors}, status=400)

    point = Point(form.cleaned_data["lng"], form.cleaned_data["lat"], srid=4326)
    update_property(property=property, location=point, actor=request.user)
    return JsonResponse({"saved": True})


