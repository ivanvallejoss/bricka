"""
Management command: seed_demo_data

Pobla la base de datos con datos demo realistas para testear la vertical
de templates properties/ — la más amplia porque integra billing, documents
y contacts.

IDEMPOTENCIA
  Busca el usuario sentinel 'bricka_demo'. Si existe y no se pasó --reset,
  avisa y sale sin tocar nada.

  --reset: elimina todos los registros cuyo created_by sea bricka_demo y
  resembrar desde cero.

_raw_delete EN RESET
  Los modelos con AuditableMixin sobreescriben QuerySet.delete() para
  lanzar AuditViolationError. _raw_delete() bypasea ese guard y los
  signals de Django. Excepción documentada y acotada a este comando de
  desarrollo — mismo patrón que hard_delete_document en documents/services.py.

SEQUENCES DE BILLING
  nextval() no se revierte con rollback de transacción (comportamiento
  propio de Postgres). Si la siembra falla parcialmente, los números de
  secuencia habrán avanzado igualmente. Trade-off documentado en
  docs/decisions/design.md.

BADGES (válidos cuando hoy está entre los días 6 y 24 del mes)
  - contract_paid:    payment_due_day=5  + recibo emitido → PAID
  - contract_overdue: payment_due_day=5  + sin recibo     → OVERDUE  (hoy > 5)
  - contract_pending: payment_due_day=25 + sin recibo     → PENDING  (hoy < 25)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from django.contrib.gis.geos import Point
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.billing.choices import ConceptLineType, DocumentStatus, DocumentType
from apps.billing.concept import ConceptLine
from apps.billing.models import BillingDocument
from apps.billing.services import create_billing_document
from apps.common.choices import Currency
from apps.contacts.choices import ContactRole, ContactSource, ContactType
from apps.contacts.models import Contact, SearchPreference
from apps.contacts.services import create_contact
from apps.contracts.choices import AdjustmentIndex, GuaranteeType
from apps.contracts.models import RentalContract, RentAdjustment
from apps.contracts.services import (
    create_rental_contract,
    expire_contract,
    terminate_contract,
)
from apps.deals.choices import DealOutcome, DealType
from apps.deals.models import Deal, DealStageHistory
from apps.deals.services import close_deal, create_deal
from apps.documents.models import Document
from apps.documents.services import DocumentUploadItem, upload_documents
from apps.listings.choices import ListingStatus, OperationType, PricePeriod
from apps.listings.models import Listing, ListingPriceHistory, ListingPublication
from apps.listings.services import create_listing, update_listing_status
from apps.properties.choices import PropertyType
from apps.properties.models import Property, PropertyMedia, ExternalPropertySource
from apps.properties.services import create_property, upload_property_media


_DEMO_MODELS = [
    BillingDocument, Document, RentAdjustment, RentalContract,
    DealStageHistory, Deal, ListingPublication, ListingPriceHistory,
    Listing, PropertyMedia, ExternalPropertySource, Property,
    SearchPreference, Contact,
]
_BILLING_SEQUENCES = (
    "billing_rent_receipt_seq",
    "billing_commission_receipt_seq",
    "billing_expense_receipt_seq",
    "billing_owner_statement_seq",
)


class Command(BaseCommand):
    help = (
        "Siembra datos demo para testear templates de properties/. "
        "Idempotente — detecta el usuario sentinel 'bricka_demo'. "
        "Usar --reset para eliminar y resembrar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Elimina todos los datos demo existentes antes de resembrar.",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if options["reset"]:
            self.stdout.write("→ Eliminando datos demo anteriores...")
            self._reset(User)
            self.stdout.write(self.style.SUCCESS("✓ Reset completo."))

        if User.objects.filter(username="bricka_demo").exists():
            self.stdout.write(
                self.style.WARNING(
                    "Los datos demo ya existen. "
                    "Usá --reset para eliminar y resembrar."
                )
            )
            return

        self.stdout.write("→ Sembrando datos demo...")
        try:
            with transaction.atomic():
                self._seed(User)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"✗ Error durante la siembra: {exc}"))
            raise

        self.stdout.write(self.style.SUCCESS("✓ Datos demo sembrados correctamente."))

    # ------------------------------------------------------------------ #
    # Reset                                                                #
    # ------------------------------------------------------------------ #

    def _reset(self, User):
        """
        Vacía las tablas de la app y reinicia la numeración de billing.

        TRUNCATE ... CASCADE no depende de created_by, ni del orden de FK,
        ni del collector. Cierra los dos modos de fallo del borrado por lista:
        filas creadas por otros usuarios/sistema sobre data demo, e hijos
        CASCADE / referrers SET_NULL que _raw_delete no neutralizaba.

        La completitud la garantiza Postgres: CASCADE trunca toda tabla que
        referencie a las listadas, figure o no en _DEMO_MODELS.

        GUARD: solo con DEBUG=True. Es un borrado TOTAL de esas tablas —
        nunca contra una base con datos a conservar. Si tu local corre con
        DEBUG=False, cambiá el guard por un chequeo del nombre de la base.
        """
        if not settings.DEBUG:
            raise CommandError(
                "Reset deshabilitado fuera de DEBUG: es un TRUNCATE total."
            )

        tables = ", ".join(model._meta.db_table for model in _DEMO_MODELS)

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE;")

            # Sequences de billing: standalone (creadas por migración, no
            # owned-by-column) → RESTART IDENTITY no las toca. Reinicio manual
            # para que el reseed numere desde 1.
            for sequence in _BILLING_SEQUENCES:
                cursor.execute(f"ALTER SEQUENCE {sequence} RESTART WITH 1;")

            # El usuario demo no vive en las tablas truncadas. Se borra
            # explícito para que _seed pueda recrearlo. _raw_delete porque
            # User es auditado y .delete() levantaría AuditViolationError.
            User.all_objects.filter(
                username="bricka_demo"
            )._raw_delete(using="default")

        self.stdout.write("  Tablas vaciadas, numeración de billing reiniciada.")

    # ------------------------------------------------------------------ #
    # Seed                                                                 #
    # ------------------------------------------------------------------ #

    def _seed(self, User):

        # ── User ─────────────────────────────────────────────────────────
        self._step("Creando usuario demo")
        demo_user = User.objects.create_user(
            username="bricka_demo",
            email="demo@bricka.com",
            password="bricka_demo_2026",
            first_name="Demo",
            last_name="Bricka",
        )

        # ── Contacts ─────────────────────────────────────────────────────
        self._step("Creando contactos")

        owner_rico = create_contact(
            full_name="Ricardo Velázquez",
            email="rvelazquez@example.com",
            phone="3624-100200",
            document_type="dni",
            document_number="18345678",
            role=ContactRole.OWNER,
            source=ContactSource.REFERRAL,
            actor=demo_user,
        )
        tenant_paid = create_contact(
            full_name="Lucía Fernández",
            email="lfernandez@example.com",
            phone="3624-200300",
            document_type="dni",
            document_number="30111222",
            role=ContactRole.TENANT,
            source=ContactSource.ZONAPROP,
            actor=demo_user,
        )
        tenant_overdue = create_contact(
            full_name="Martín Romero",
            email="mromero@example.com",
            phone="3624-300400",
            document_type="dni",
            document_number="25333444",
            role=ContactRole.TENANT,
            source=ContactSource.FACEBOOK,
            actor=demo_user,
        )
        tenant_pending = create_contact(
            full_name="Sofía Giménez",
            email="sgimenez@example.com",
            phone="3624-400500",
            document_type="dni",
            document_number="35555666",
            role=ContactRole.TENANT,
            source=ContactSource.WHATSAPP,
            actor=demo_user,
        )
        tenant_expired = create_contact(
            full_name="Carlos Miño",
            email="cmino@example.com",
            phone="3624-500600",
            role=ContactRole.TENANT,
            source=ContactSource.DIRECT,
            actor=demo_user,
        )
        tenant_terminated = create_contact(
            full_name="Ana Riquelme",
            email="ariquelme@example.com",
            phone="3624-600700",
            role=ContactRole.TENANT,
            source=ContactSource.DIRECT,
            actor=demo_user,
        )
        # Receptores del split de comisión
        comision_a = create_contact(
            full_name="Inmobiliaria Asociada S.R.L.",
            contact_type=ContactType.COMPANY,
            email="contacto@inmoasociada.com.ar",
            phone="3624-700800",
            document_type="cuit",
            document_number="3071234567",
            source=ContactSource.REFERRAL,
            actor=demo_user,
        )
        comision_b = create_contact(
            full_name="Jorge Suárez",
            email="jsuarez@example.com",
            phone="3624-800900",
            document_type="dni",
            document_number="22888999",
            source=ContactSource.DIRECT,
            actor=demo_user,
        )

        # ── Properties ───────────────────────────────────────────────────
        self._step("Creando propiedades")

        # Propiedad rica — listing activo, contrato ACTIVE, billing completo,
        # documentos y foto de portada. Es el caso de prueba central.
        prop_rico = self._make_property(
            title="Departamento 3 ambientes — Centro",
            description=(
                "Luminoso departamento en el corazón del centro. "
                "Tres ambientes amplios, cocina equipada, balcón con vista "
                "a la plaza. Edificio con portería y ascensor."
            ),
            property_type=PropertyType.APARTMENT,
            address_line="San Martín 1250, Piso 4, Dpto. B",
            city="Resistencia",
            neighborhood="Centro",
            province="Chaco",
            area_m2=Decimal("85.00"),
            bedrooms=3,
            bathrooms=2,
            year_built=2008,
            owner_contact_id=owner_rico.pk,
            actor=demo_user,
        )
        prop_overdue = self._make_property(
            title="Casa 3 dormitorios — Villa del Parque",
            description="Casa familiar con jardín y garaje. Ideal para familia numerosa.",
            property_type=PropertyType.HOUSE,
            address_line="Av. 25 de Mayo 890",
            city="Resistencia",
            neighborhood="Villa del Parque",
            province="Chaco",
            area_m2=Decimal("120.00"),
            bedrooms=3,
            bathrooms=1,
            owner_contact_id=owner_rico.pk,
            actor=demo_user,
        )
        prop_pending = self._make_property(
            title="Monoambiente — Barrio Norte",
            description="Monoambiente moderno. Ideal para estudiante o profesional.",
            property_type=PropertyType.APARTMENT,
            address_line="Laprida 450, Piso 2, Dpto. A",
            city="Resistencia",
            neighborhood="Barrio Norte",
            province="Chaco",
            area_m2=Decimal("55.00"),
            bedrooms=1,
            bathrooms=1,
            owner_contact_id=owner_rico.pk,
            actor=demo_user,
        )
        prop_programada = self._make_property(
            title="Departamento 2 ambientes — España",
            description=(
                "Departamento con vista despejada. "
                "Contrato de alquiler programado para septiembre 2026. "
                "En venta simultáneamente."
            ),
            property_type=PropertyType.APARTMENT,
            address_line="España 1100, Piso 7, Dpto. C",
            city="Resistencia",
            neighborhood="Centro",
            province="Chaco",
            area_m2=Decimal("70.00"),
            bedrooms=2,
            bathrooms=1,
            actor=demo_user,
        )
        prop_expired = self._make_property(
            title="Oficina — Alberdi",
            description="Oficina en piso alto, pleno microcentro. Contrato vencido.",
            property_type=PropertyType.OFFICE,
            address_line="Av. Alberdi 320, Piso 3",
            city="Resistencia",
            province="Chaco",
            area_m2=Decimal("45.00"),
            actor=demo_user,
        )
        prop_terminated = self._make_property(
            title="Casa 4 dormitorios — Forestación",
            description="Casa amplia con jardín. Contrato rescindido anticipadamente.",
            property_type=PropertyType.HOUSE,
            address_line="Pellegrini 780",
            city="Resistencia",
            neighborhood="Villa Forestación",
            province="Chaco",
            area_m2=Decimal("150.00"),
            bedrooms=4,
            bathrooms=2,
            actor=demo_user,
        )

        # Foto de portada para prop_rico.
        # r2_key ficticio — en dev build_media_url devuelve URL rota pero
        # el template no crashea: permite testear la lógica de portada.
        upload_property_media(
            property=prop_rico,
            r2_key="demo/prop_rico/foto_principal.jpg",
            mime_type="image/jpeg",
            order=0,
            actor=demo_user,
        )

        # ── Listings ─────────────────────────────────────────────────────
        self._step("Creando listings")

        listing_rent_rico = create_listing(
            property=prop_rico,
            operation_type=OperationType.RENT,
            price=Decimal("380000.00"),
            currency=Currency.ARS,
            period=PricePeriod.MONTHLY,
            actor=demo_user,
        )
        update_listing_status(
            listing=listing_rent_rico,
            status=ListingStatus.PUBLISHED,
            actor=demo_user,
        )

        listing_venta_programada = create_listing(
            property=prop_programada,
            operation_type=OperationType.SALE,
            price=Decimal("95000.00"),
            currency=Currency.USD,
            period=PricePeriod.TOTAL,
            actor=demo_user,
        )
        update_listing_status(
            listing=listing_venta_programada,
            status=ListingStatus.PUBLISHED,
            actor=demo_user,
        )

        # ── Deals ────────────────────────────────────────────────────────
        self._step("Creando deals")

        # Deal WON con propiedad externa — no modifica status de ninguna
        # property de demo. Base para el split de comisión en billing.
        deal_won = create_deal(
            deal_type=DealType.RENT,
            client_contact_id=tenant_paid.pk,
            external_property_notes=(
                "Alquiler Depto. San Martín 1250 — "
                "comisión compartida con Inmobiliaria Asociada S.R.L."
            ),
            actor=demo_user,
        )
        close_deal(deal=deal_won, outcome=DealOutcome.WON, actor=demo_user)

        # Deal abierto sobre listing activo — representa pipeline en curso.
        create_deal(
            deal_type=DealType.RENT,
            client_contact_id=tenant_pending.pk,
            listing_id=listing_rent_rico.pk,
            notes="Cliente interesada. Visita coordinada para fin de mes.",
            actor=demo_user,
        )

        # ── Rental Contracts ─────────────────────────────────────────────
        self._step("Creando contratos")

        # ACTIVE — payment_due_day=5. Hoy=18 > 5 pero tiene recibo emitido
        # para junio → badge PAID.
        contract_paid = create_rental_contract(
            property_id=prop_rico.pk,
            tenant_contact_id=tenant_paid.pk,
            owner_contact_id=owner_rico.pk,
            start_date=date(2025, 7, 1),
            end_date=date(2027, 6, 30),
            initial_price=Decimal("320000.00"),
            currency=Currency.ARS,
            payment_due_day=5,
            adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3,
            guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
            guarantee_detail="Garantía propietaria: Pellegrini 450, Resistencia.",
            deposit_amount=Decimal("320000.00"),
            actor=demo_user,
        )

        # ACTIVE — payment_due_day=5. Hoy=18 > 5, sin recibo → badge OVERDUE.
        contract_overdue = create_rental_contract(
            property_id=prop_overdue.pk,
            tenant_contact_id=tenant_overdue.pk,
            owner_contact_id=owner_rico.pk,
            start_date=date(2025, 3, 1),
            end_date=date(2027, 2, 28),
            initial_price=Decimal("280000.00"),
            currency=Currency.ARS,
            payment_due_day=5,
            adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3,
            guarantee_type=GuaranteeType.INSURANCE,
            actor=demo_user,
        )

        # ACTIVE — payment_due_day=25. Hoy=18 < 25, sin recibo → badge PENDING.
        contract_pending = create_rental_contract(
            property_id=prop_pending.pk,
            tenant_contact_id=tenant_pending.pk,
            owner_contact_id=owner_rico.pk,
            start_date=date(2026, 2, 1),
            end_date=date(2028, 1, 31),
            initial_price=Decimal("180000.00"),
            currency=Currency.ARS,
            payment_due_day=25,
            adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3,
            guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
            actor=demo_user,
        )

        # SCHEDULED — start_date futuro. create_rental_contract detecta
        # start_date > today y asigna status=SCHEDULED sin tocar property.
        create_rental_contract(
            property_id=prop_programada.pk,
            tenant_contact_id=tenant_pending.pk,
            owner_contact_id=owner_rico.pk,
            start_date=date(2026, 9, 1),
            end_date=date(2028, 8, 31),
            initial_price=Decimal("250000.00"),
            currency=Currency.ARS,
            payment_due_day=10,
            adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3,
            guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
            actor=demo_user,
        )

        # EXPIRED — creado ACTIVE (start_date pasado), luego expirado
        # vía service. Side effect: prop_expired.status = AVAILABLE.
        contract_expired = create_rental_contract(
            property_id=prop_expired.pk,
            tenant_contact_id=tenant_expired.pk,
            owner_contact_id=owner_rico.pk,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            initial_price=Decimal("120000.00"),
            currency=Currency.ARS,
            payment_due_day=10,
            adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3,
            guarantee_type=GuaranteeType.INSURANCE,
            actor=demo_user,
        )
        expire_contract(contract=contract_expired, actor=demo_user)

        # TERMINATED — creado ACTIVE, luego rescindido vía service.
        # Side effect: prop_terminated.status = AVAILABLE.
        contract_terminated = create_rental_contract(
            property_id=prop_terminated.pk,
            tenant_contact_id=tenant_terminated.pk,
            owner_contact_id=owner_rico.pk,
            start_date=date(2025, 9, 1),
            end_date=date(2027, 8, 31),
            initial_price=Decimal("350000.00"),
            currency=Currency.ARS,
            payment_due_day=15,
            adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3,
            guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
            actor=demo_user,
        )
        terminate_contract(contract=contract_terminated, actor=demo_user)

        # ── Billing Documents ─────────────────────────────────────────────
        self._step("Creando comprobantes")

        # 1. RENT_RECEIPT junio 2026 — genera badge PAID en contract_paid.
        create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[
                ConceptLine(
                    type=ConceptLineType.RENT,
                    description="Alquiler junio 2026",
                    amount=Decimal("380000.00"),
                ),
            ],
            date=date(2026, 6, 5),
            period=date(2026, 6, 1),
            contract=contract_paid,
            actor=demo_user,
        )

        # 2. RENT_RECEIPT mayo 2026 — cancelado + reemitido.
        #    Demuestra que el índice parcial permite N CANCELLED + 1 ISSUED
        #    sobre el mismo (contract, period).
        may_receipt = create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[
                ConceptLine(
                    type=ConceptLineType.RENT,
                    description="Alquiler mayo 2026 (primera emisión — importe erróneo)",
                    amount=Decimal("320000.00"),
                ),
            ],
            date=date(2026, 5, 5),
            period=date(2026, 5, 1),
            contract=contract_paid,
            actor=demo_user,
        )
        # Cancelación manual — no existe service de cancelación todavía.
        # updated_by seteado explícitamente como adelanto del patrón
        # que deberá seguir el service formal cuando se escriba.
        may_receipt.status = DocumentStatus.CANCELLED
        may_receipt.updated_by = demo_user
        may_receipt.save(update_fields=["status", "updated_by", "updated_at"])

        # Reemisión del mismo período — el índice parcial lo permite.
        create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[
                ConceptLine(
                    type=ConceptLineType.RENT,
                    description="Alquiler mayo 2026",
                    amount=Decimal("380000.00"),
                ),
                ConceptLine(
                    type=ConceptLineType.MORA,
                    description="Mora por pago fuera de término (5 días)",
                    amount=Decimal("3800.00"),
                ),
            ],
            date=date(2026, 5, 10),
            period=date(2026, 5, 1),
            contract=contract_paid,
            actor=demo_user,
        )

        # 3. OWNER_STATEMENT — Ricardo Velázquez, junio 2026.
        #    Consolida dos contratos en un único documento de rendición.
        #    contract_id en cada renglón reemplaza la FK directa (V1).
        create_billing_document(
            document_type=DocumentType.OWNER_STATEMENT,
            lines=[
                ConceptLine(
                    type=ConceptLineType.RENT,
                    description="Alquiler San Martín 1250 — junio 2026",
                    amount=Decimal("380000.00"),
                    contract_id=str(contract_paid.pk),
                ),
                ConceptLine(
                    type=ConceptLineType.COMMISSION,
                    description="Comisión administración San Martín 1250",
                    amount=Decimal("38000.00"),
                    contract_id=str(contract_paid.pk),
                ),
                ConceptLine(
                    type=ConceptLineType.RENT,
                    description="Alquiler 25 de Mayo 890 — mayo 2026",
                    amount=Decimal("280000.00"),
                    contract_id=str(contract_overdue.pk),
                ),
                ConceptLine(
                    type=ConceptLineType.COMMISSION,
                    description="Comisión administración 25 de Mayo 890",
                    amount=Decimal("28000.00"),
                    contract_id=str(contract_overdue.pk),
                ),
            ],
            date=date(2026, 6, 10),
            period=date(2026, 6, 1),
            recipient_contact=owner_rico,
            actor=demo_user,
        )

        # 4. COMMISSION_RECEIPT split — mismo deal, dos receptores distintos.
        #    Caso más complejo del modelo: dos comprobantes por un único cierre.
        create_billing_document(
            document_type=DocumentType.COMMISSION_RECEIPT,
            lines=[
                ConceptLine(
                    type=ConceptLineType.COMMISSION,
                    description="Comisión 50% — Inmobiliaria Asociada S.R.L.",
                    amount=Decimal("19000.00"),
                ),
            ],
            date=date(2026, 6, 5),
            deal=deal_won,
            recipient_contact=comision_a,
            actor=demo_user,
        )
        create_billing_document(
            document_type=DocumentType.COMMISSION_RECEIPT,
            lines=[
                ConceptLine(
                    type=ConceptLineType.COMMISSION,
                    description="Comisión 50% — Jorge Suárez",
                    amount=Decimal("19000.00"),
                ),
            ],
            date=date(2026, 6, 5),
            deal=deal_won,
            recipient_contact=comision_b,
            actor=demo_user,
        )

        # ── Documents ─────────────────────────────────────────────────────
        self._step("Creando documentos")

        # r2_keys ficticios — en dev generate_document_url devuelve
        # /media/demo/... (inaccesible), pero el template carga y permite
        # verificar que la lógica de listado y categorización funciona.
        upload_documents(
            items=[
                DocumentUploadItem(
                    r2_key="demo/prop_rico/contrato_alquiler.pdf",
                    original_filename="Contrato de Alquiler — San Martín 1250.pdf",
                    content_type="application/pdf",
                    file_size=245_760,
                    description="Contrato de alquiler firmado — vigente",
                ),
                DocumentUploadItem(
                    r2_key="demo/prop_rico/escritura.pdf",
                    original_filename="Escritura de Propiedad.pdf",
                    content_type="application/pdf",
                    file_size=512_000,
                    description="Escritura de dominio",
                ),
                DocumentUploadItem(
                    r2_key="demo/prop_rico/plano_planta.jpg",
                    original_filename="Plano de Planta — Unidad 4B.jpg",
                    content_type="image/jpeg",
                    file_size=102_400,
                    description="Plano de planta aprobado por municipio",
                ),
            ],
            property_id=prop_rico.pk,
            contract_id=contract_paid.pk,
            actor=demo_user,
        )

        self._summary()

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _step(self, message: str) -> None:
        self.stdout.write(f"  {message}...")

    def _make_property(self, *, title: str, description: str, actor, **kwargs) -> Property:
        """
        Crea una propiedad vía service y le añade title + description.

        create_property no expone esos campos como parámetros todavía —
        se parchean con un segundo save(). Revisitar cuando el service
        los incorpore formalmente.
        """
        prop = create_property(**kwargs, actor=actor)
        prop.title = title
        prop.description = description
        prop.save(update_fields=["title", "description", "updated_at"])
        return prop

    def _summary(self) -> None:
        self.stdout.write(
            "\n"
            "  ─────────────────────────────────────────────────────────\n"
            "  Usuarios:      1   (bricka_demo / bricka_demo_2026)\n"
            "  Contactos:     8   (1 propietario, 4 inquilinos, 1 expirado,\n"
            "                      1 rescindido, 2 comisión)\n"
            "  Propiedades:   6   (1 con foto de portada)\n"
            "  Listings:      2   (RENT ARS + SALE USD, ambos PUBLISHED)\n"
            "  Deals:         2   (1 WON, 1 abierto)\n"
            "  Contratos:     6   (ACTIVE×3, SCHEDULED, EXPIRED, TERMINATED)\n"
            "  Comprobantes:  6   (PAID, cancelado, reemitido+mora,\n"
            "                      OWNER_STATEMENT, COMMISSION×2 split)\n"
            "  Documentos:    3   (r2_keys ficticios — dev sin R2)\n"
            "  ─────────────────────────────────────────────────────────\n"
            "\n"
            "  Badges esperados (válidos cuando hoy está entre días 6-24):\n"
            "    prop_rico      → PAID    (payment_due_day=5, recibo emitido)\n"
            "    prop_overdue   → OVERDUE (payment_due_day=5, sin recibo)\n"
            "    prop_pending   → PENDING (payment_due_day=25, sin recibo)\n"
            "  ─────────────────────────────────────────────────────────"
        )