import json
from uuid import UUID

from datetime import date

from django.shortcuts import render, redirect
from django.http import Http404, HttpResponse, HttpResponseNotAllowed, JsonResponse
from django.core.paginator import Paginator
from django.core.exceptions import ObjectDoesNotExist
from django.contrib import messages

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
from .forms import PropertyForm, PropertyCreateForm, ListingCreateForm, ListingPriceForm
from .choices import FeatureCategory, PropertyType

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

from apps.contacts.models import Contact

from apps.contracts.selectors import get_active_contract_for_property

from apps.documents.selectors import get_document_list, DocumentFilters
from apps.documents.context import DocumentContext
from apps.documents.utils import categorize_document

from apps.listings.selectors import get_listings_for_property, get_listing_detail
from apps.listings.services import (
    MIN_PHOTOS_TO_PUBLISH, MIN_DESCRIPTION_LENGTH,
    create_listing, update_listing_status, update_listing_price,
)
from apps.listings.exceptions import ListingValidationError, ListingPublicationRequirementsError
from apps.listings.choices import OperationType, PricePeriod, ListingStatus
from .checklist import FLOW_EDIT, FLOW_WIZARD, build_publication_checklist


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
    Fase 2 del wizard (§1): detalle. Reusa el form escalar (§5) — sin bloques
    externas/location (S3b). Ambos submits guardan (la fase persiste, §1):
    "Guardar y salir" → detail; "Siguiente" → fotos (W3 lo reapunta; hoy a
    detail temporal).
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