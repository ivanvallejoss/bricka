from django.db import models


class InboundChannel(models.TextChoices):
    ZONAPROP = "zonaprop", "Zonaprop"
    OWN_WEBSITE = "own_website", "Sitio propio"
    FACEBOOK = "facebook", "Facebook"
    INSTAGRAM = "instagram", "Instagram"
    WHATSAPP = "whatsapp", "WhatsApp"


class InboundEventStatus(models.TextChoices):
    PENDING = "pending", "Pendiente"
    PROCESSING = "processing", "Procesando"
    PROCESSED = "processed", "Procesado"
    FAILED = "failed", "Fallido"


class OutboundEventStatus(models.TextChoices):
    PENDING = "pending", "Pendiente"
    PROCESSING = "processing", "Procesando"
    DELIVERED = "delivered", "Entregado"
    FAILED = "failed", "Fallido"


class EventType:
    """
    Contratos de event_type para OutboundEvent e InboundEvent.
    El campo en DB es varchar — estas constantes son el contrato en código.
    Ningún writer usa string literals directamente.

    Para agregar un tipo nuevo:
    1. Definir la constante aquí
    2. Agregar al set ALL_OUTBOUND o ALL_INBOUND
    3. Implementar el handler en integrations/handlers/
    El service valida contra esos sets antes de persistir.
    """
    # Outbound
    ZONAPROP_LISTING_PUBLISH = "zonaprop.listing.publish"
    ZONAPROP_LISTING_UNPUBLISH = "zonaprop.listing.unpublish"
    FACEBOOK_LISTING_PUBLISH = "facebook.listing.publish"
    WHATSAPP_LEAD_NOTIFY = "whatsapp.lead.notify"

    # Inbound
    ZONAPROP_LEAD_RECEIVED = "zonaprop.lead.received"
    FACEBOOK_LEAD_RECEIVED = "facebook.lead.received"
    WHATSAPP_MESSAGE_RECEIVED = "whatsapp.message.received"

    ALL_OUTBOUND = {
        ZONAPROP_LISTING_PUBLISH,
        ZONAPROP_LISTING_UNPUBLISH,
        FACEBOOK_LISTING_PUBLISH,
        WHATSAPP_LEAD_NOTIFY,
    }

    ALL_INBOUND = {
        ZONAPROP_LEAD_RECEIVED,
        FACEBOOK_LEAD_RECEIVED,
        WHATSAPP_MESSAGE_RECEIVED,
    }