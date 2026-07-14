"""
Management command: seed_test_data

Siembra data de prueba para testear flujos (crear/editar/borrar/listar) en las
cuatro verticales. Organizado por clusters narrativos coherentes, no por tabla.
Anclado a date.today() para badges deterministas. --reset trunca y resiembra.

Reemplaza a seed_demo_data (a eliminar una vez que esto corra verde de punta
a punta).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.common.choices import Currency
from apps.billing.choices import ConceptLineType, DocumentType
from apps.billing.concept import ConceptLine
from apps.billing.models import BillingDocument
from apps.billing.services import create_billing_document
from apps.contacts.models import Contact, SearchPreference
from apps.contacts.choices import ContactRole, ContactSource, ContactType   # +ContactType
from apps.contacts.services import archive_contact, create_contact, create_contact     # +archive_contact
from apps.contracts.choices import AdjustmentIndex, GuaranteeType
from apps.contracts.models import RentalContract, RentAdjustment
from apps.contracts.services import apply_rent_adjustment, create_rental_contract, expire_contract, terminate_contract
from apps.deals.models import Deal, DealStageHistory
from apps.deals.choices import DealOutcome, DealType
from apps.deals.services import close_deal, create_deal
from apps.documents.models import Document
from apps.listings.choices import (
    ListingStatus, OperationType, PricePeriod, PublicationChannel, PublicationStatus,
) 
from apps.listings.models import Listing, ListingPriceHistory, ListingPublication
from apps.listings.services import (
    create_listing, create_listing_publication, update_listing_price,
    update_listing_status, update_publication_status,
) 

from apps.common.storage import build_media_key
from apps.properties.choices import PropertyType, PropertyStatus
from apps.properties.models import ExternalPropertySource, Property, PropertyMedia
from apps.properties.services import create_property, upload_property_media
from apps.operations.services import withdraw_property

_SENTINEL_USERNAME = "bricka_seed"

# Tablas que el reset vacía. CASCADE alcanza cualquiera que las referencie,
# esté o no acá; la lista es por claridad/auditabilidad.
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

# Coordenadas reales de Resistencia, Chaco. Tuplas (lon, lat) — SRID 4326.
# Point(x, y) = Point(lon, lat): invertir el orden cae en el océano.
_RESISTENCIA_POINTS = {
    "centro":            (-58.9868, -27.4516),
    "villa_sarmiento":   (-58.9712, -27.4378),
    "espana":            (-58.9889, -27.4602),
    "villa_del_parque":  (-59.0048, -27.4489),
    "barrio_norte":      (-58.9790, -27.4401),
    "guemes":            (-58.9935, -27.4470),
    "san_fernando":      (-58.9690, -27.4520),
    "villa_forestacion": (-59.0010, -27.4395),
    "villa_libertad":    (-58.9760, -27.4280),
    "villa_chica":       (-58.9700, -27.4550),
    "ejido_norte":       (-59.0200, -27.4100),
}


class Command(BaseCommand):
    help = (
        "Siembra data de prueba para testear flujos en las cuatro verticales. "
        "--reset trunca todas las tablas de la app antes de resembrar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Trunca todas las tablas de la app antes de resembrar.",
        )
        parser.add_argument(
            "--noinput", "--no-input", action="store_false", dest="interactive",
            help="No pedir confirmación interactiva (CI/tests).",
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if options["reset"]:
            self._confirm_reset(interactive=options["interactive"])
            self.stdout.write("→ Truncando tablas...")
            self._reset(User)
            self.stdout.write(self.style.SUCCESS("✓ Reset completo."))

        if User.objects.filter(username=_SENTINEL_USERNAME).exists():
            self.stdout.write(self.style.WARNING(
                "La data ya existe. Usá --reset para resembrar."))
            return

        self.stdout.write("→ Sembrando...")
        try:
            with transaction.atomic():
                self._seed(User)
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"✗ Error en la siembra: {exc}"))
            raise
        self.stdout.write(self.style.SUCCESS("✓ Data sembrada."))

    # ── Seguridad ──────────────────────────────────────────────────────
    def _confirm_reset(self, *, interactive: bool) -> None:
        # Muro: nunca contra prod, ni por script ni por reflejo.
        if not settings.DEBUG:
            raise CommandError(
                "Reset deshabilitado fuera de DEBUG: es un TRUNCATE total.")
        # Speed-bump: fat-finger interactivo. --noinput lo saltea (CI/tests).
        if not interactive:
            return
        self.stdout.write(self.style.WARNING(
            "Vas a TRUNCAR todas las tablas de la app. Se pierde TODA la data."))
        answer = input("Escribí 'si' para continuar: ").strip().lower()
        if answer not in {"si", "sí", "yes"}:
            raise CommandError("Reset cancelado.")

    def _reset(self, User):
        """
        Vacía las tablas de la app y reinicia la numeración de billing.
        El guard DEBUG + la confirmación ya corrieron en _confirm_reset.

        TRUNCATE ... CASCADE no depende de created_by, ni del orden de FK,
        ni del collector. La completitud la garantiza Postgres.
        """
        tables = ", ".join(model._meta.db_table for model in _DEMO_MODELS)
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE;")
            # Sequences de billing: standalone (no owned-by-column) →
            # RESTART IDENTITY no las toca. Reinicio manual para numerar desde 1.
            for sequence in _BILLING_SEQUENCES:
                cursor.execute(f"ALTER SEQUENCE {sequence} RESTART WITH 1;")
            # El sentinel no vive en las tablas truncadas; se borra explícito
            # para que _seed pueda recrearlo. _raw_delete: User es auditado.
            User.all_objects.filter(
                username=_SENTINEL_USERNAME
            )._raw_delete(using="default")
        self.stdout.write("  Tablas vaciadas, numeración de billing reiniciada.")

    # ── Orquestador ────────────────────────────────────────────────────
    def _seed(self, User):
        sentinel = User.objects.create_user(
            username=_SENTINEL_USERNAME, email="seed@bricka.com",
            password="bricka_seed_2026", first_name="Seed", last_name="Bricka",
        )
        today = date.today()
        ctx = {"actor": sentinel, "today": today, "period": today.replace(day=1)}

        ctx["a"] = self._cluster_a_al_dia(ctx)
        ctx["b"] = self._cluster_b_mora(ctx)
        ctx["c"] = self._cluster_c_ajuste_pendiente(ctx)
        ctx["d"] = self._cluster_d_venta(ctx)
        ctx["e"] = self._cluster_e_programado(ctx)
        ctx["f"] = self._cluster_f_ciclos(ctx)
        ctx["g"] = self._cluster_g_externa(ctx)
        ctx["h"] = self._cluster_h_pipeline(ctx)
        self._bordes_sueltos(ctx)
        self._cluster_consolidacion(ctx)
        # Cluster C–H + consolidación: se agregan acá a medida que los generamos.

        self._summary()

    # ── Helpers ────────────────────────────────────────────────────────
    def _step(self, message: str) -> None:
        self.stdout.write(f"  {message}...")

    def _point(self, key: str) -> Point:
        lon, lat = _RESISTENCIA_POINTS[key]
        return Point(lon, lat, srid=4326)

    def _summary(self) -> None:
        self.stdout.write(
            "\n  ───────────────────────────────\n"
            f"  Contactos:    {Contact.objects.count()}\n"
            f"  Propiedades:  {Property.objects.count()}\n"
            f"  Listings:     {Listing.objects.count()}\n"
            f"  Contratos:    {RentalContract.objects.count()}\n"
            f"  Comprobantes: {BillingDocument.objects.count()}\n"
            "  ───────────────────────────────\n"
            f"  Sentinel: {_SENTINEL_USERNAME} / bricka_seed_2026"
        )

    def _mora(self, contract, days_late: int) -> Decimal:
        """
        Mora compuesta diaria — misma fórmula que selectors.calculate_mora.
        Replicada (no llamada) porque calculate_mora deriva los días de
        as_of vs payment_due_day del mes en curso; acá fijamos days_late
        para un recibo de un período pasado.
        """
        rate = contract.late_fee_percent_daily
        factor = (Decimal("1") + rate / Decimal("100")) ** days_late - Decimal("1")
        return (contract.current_price * factor).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


    def _media(self, *, prop, actor, count: int = 2) -> None:
        """
        Siembra PropertyMedia con keys sintéticas: formato real vía
        build_media_key, SIN objeto en R2 (decisión S1: el seed corre en
        CI y entornos sin credenciales — las <img> en dev renderizan
        rotas hasta S3). Viola a propósito la precondición del service
        ("r2_key ya subido"): no lo "arregles" subiendo archivos acá.
        La primera foto queda cover por lógica del service, no del seed.
        """
        for i in range(count):
            upload_property_media(
                property=prop,
                r2_key=build_media_key(
                    property_id=prop.pk, filename=f"seed-{i}.jpg"
                ),
                mime_type="image/jpeg",
                order=i,
                actor=actor,
            )


    # ── Clusters ───────────────────────────────────────────────────────
    def _cluster_a_al_dia(self, ctx):
        """
        Cluster A — Inmueble administrado al día.
        ACTIVE con ajuste ICL aplicado (current_price lo refleja), recibo del
        período → PAID cualquier día. Listing que rentó queda CLOSED con
        historial de precio. Media sintética (keys sin objeto en R2).
        """
        self._step("Cluster A — administrado al día")
        actor, today, period = ctx["actor"], ctx["today"], ctx["period"]

        owner = create_contact(
            full_name="Ricardo Velázquez", email="rvelazquez@example.com",
            phone="362-4100200", document_type="dni", document_number="18345678",
            role=ContactRole.OWNER, source=ContactSource.REFERRAL, actor=actor,
        )
        tenant = create_contact(
            full_name="Lucía Fernández", email="lfernandez@example.com",
            phone="362-4200300", document_type="dni", document_number="30111222",
            role=ContactRole.TENANT, source=ContactSource.ZONAPROP, actor=actor,
        )

        prop = create_property(
            title="Departamento 3 ambientes — Centro",
            description=("Luminoso 3 ambientes sobre la peatonal, cocina "
                         "equipada y balcón a la plaza. Portería y ascensor."),
            location=self._point("centro"),
            property_type=PropertyType.APARTMENT,
            address_line="Justo XII 250, Piso 4, Dpto. B",
            city="Resistencia", neighborhood="Centro", province="Chaco",
            area_m2=Decimal("85.00"), bedrooms=3, bathrooms=2, year_built=2008,
            features=["balcon", "encargado", "ascensor", "cocina_equipada"],
            owner_contact_id=owner.pk, actor=actor,
        )

        listing = create_listing(
            property=prop, operation_type=OperationType.RENT,
            price=Decimal("320000.00"), currency=Currency.ARS,
            period=PricePeriod.MONTHLY, actor=actor,
        )
        self._media(prop=prop, actor=actor)
        update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)
        update_listing_price(listing=listing, price=Decimal("300000.00"), actor=actor)
        update_listing_status(listing=listing, status=ListingStatus.CLOSED, actor=actor)

        start = today - relativedelta(months=5)
        contract = create_rental_contract(
            property_id=prop.pk, tenant_contact_id=tenant.pk, owner_contact_id=owner.pk,
            start_date=start, end_date=start + relativedelta(months=24),
            initial_price=Decimal("300000.00"), currency=Currency.ARS,
            payment_due_day=10, adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3, guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
            guarantee_detail="Garantía propietaria: French 540, Resistencia.",
            deposit_amount=Decimal("300000.00"), actor=actor,
        )

        # next_adjustment inicial = start+3m (vencía hace ~2m); se aplica ahí →
        # current_price 300000→366000 y next_adjustment salta a futuro.
        contract = apply_rent_adjustment(
            contract=contract,
            adjustment_date=start + relativedelta(months=3),
            index_value_at_date=Decimal("22.00"),
            applied_by=actor,
        )

        create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[ConceptLine(
                type=ConceptLineType.RENT,
                description=f"Alquiler {period:%m/%Y}",
                amount=contract.current_price,
            )],
            date=today, period=period, contract=contract, actor=actor,
        )

        return {"owner": owner, "tenant": tenant, "property": prop, "contract": contract}

    def _cluster_b_mora(self, ctx):
        """
        Cluster B — Mora + expensas.
        Pagó tarde el mes pasado (RENT + MORA), no pagó el actual → OVERDUE del
        día 6 en adelante. Expensas en EXPENSE_RECEIPT aparte. Propiedad de
        Ricardo (reuso de A) → 2º contrato del mismo dueño para la consolidación.
        """
        self._step("Cluster B — mora + expensas")
        actor, today, period = ctx["actor"], ctx["today"], ctx["period"]
        owner = ctx["a"]["owner"]

        tenant = create_contact(
            full_name="Martín Romero", email="mromero@example.com",
            phone="362-4300400", document_type="dni", document_number="25333444",
            role=ContactRole.TENANT, source=ContactSource.FACEBOOK, actor=actor,
        )

        prop = create_property(
            title="Casa 3 dormitorios — Villa del Parque",
            description=("Casa familiar con patio y garaje para dos autos. "
                         "Living comedor amplio, tres dormitorios, lavadero."),
            location=self._point("villa_del_parque"),
            property_type=PropertyType.HOUSE,
            address_line="Av. 25 de Mayo 1840",
            city="Resistencia", neighborhood="Villa del Parque", province="Chaco",
            area_m2=Decimal("120.00"), bedrooms=3, bathrooms=1, year_built=1998,
            features=["patio", "lavadero"],
            parking_spaces=1,
            owner_contact_id=owner.pk, actor=actor,
        )

        listing = create_listing(
            property=prop, operation_type=OperationType.RENT,
            price=Decimal("250000.00"), currency=Currency.ARS,
            period=PricePeriod.MONTHLY, actor=actor,
        )
        self._media(prop=prop, actor=actor)
        update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)
        update_listing_status(listing=listing, status=ListingStatus.CLOSED, actor=actor)

        start = today - relativedelta(months=2)
        contract = create_rental_contract(
            property_id=prop.pk, tenant_contact_id=tenant.pk, owner_contact_id=owner.pk,
            start_date=start, end_date=start + relativedelta(months=24),
            initial_price=Decimal("250000.00"), currency=Currency.ARS,
            payment_due_day=5, adjustment_index=AdjustmentIndex.IPC,
            adjustment_frequency_months=6, guarantee_type=GuaranteeType.INSURANCE,
            guarantee_detail="Seguro de caución — Póliza 884412, Afianzar S.G.R.",
            deposit_amount=Decimal("250000.00"), actor=actor,
        )

        rent = contract.current_price  # 250000 (sin ajuste; 2 meses)
        last_period = period - relativedelta(months=1)
        days_late = 4
        mora = self._mora(contract, days_late)  # compuesta = calculate_mora → 20608.04
        create_billing_document(
            document_type=DocumentType.RENT_RECEIPT,
            lines=[
                ConceptLine(type=ConceptLineType.RENT,
                            description=f"Alquiler {last_period:%m/%Y}", amount=rent),
                ConceptLine(type=ConceptLineType.MORA,
                            description=f"Mora por pago fuera de término ({days_late} días)",
                            amount=mora),
            ],
            date=last_period.replace(day=9), period=last_period,
            contract=contract, actor=actor,
        )

        create_billing_document(
            document_type=DocumentType.EXPENSE_RECEIPT,
            lines=[ConceptLine(type=ConceptLineType.EXPENSE,
                               description=f"Expensas {period:%m/%Y}",
                               amount=Decimal("45000.00"))],
            date=today, period=period, contract=contract, actor=actor,
        )

        return {"owner": owner, "tenant": tenant, "property": prop, "contract": contract}


    def _cluster_c_ajuste_pendiente(self, ctx):
        """
        Cluster C — Ajuste pendiente (banner) + badge PENDING.

        C1: banner DANGER ("Vencido hace 10 días") — next_adjustment_date en el
            pasado, ACTIVE, sin ajuste aplicado. Índice ICL.
        C2: banner WARNING ("En ~18 días") — next_adjustment_date próxima.
            Índice FIXED_PERCENT (ejercita el check constraint con percent set).
        Ambos: due_day=28, sin recibo del período → badge PENDING. Sin listings
        (la unidad está RENTED; el listing no es invariante). Sin ajuste aplicado
        → current_price = initial_price.
        """
        self._step("Cluster C — ajuste pendiente + PENDING")
        actor, today = ctx["actor"], ctx["today"]

        owner = create_contact(
            full_name="Graciela Sosa", email="gsosa@example.com",
            phone="362-4500600", document_type="dni", document_number="16998877",
            role=ContactRole.OWNER, source=ContactSource.DIRECT, actor=actor,
        )
        tenant_c1 = create_contact(
            full_name="Diego Acuña", email="dacuna@example.com",
            phone="362-4600700", document_type="dni", document_number="33444555",
            role=ContactRole.TENANT, source=ContactSource.INSTAGRAM, actor=actor,
        )
        tenant_c2 = create_contact(
            full_name="Paula Benítez", email="pbenitez@example.com",
            phone="362-4700800", document_type="dni", document_number="29222111",
            role=ContactRole.TENANT, source=ContactSource.WHATSAPP, actor=actor,
        )

        # ── C1: banner DANGER (vencido) ──────────────────────────────────
        prop_c1 = create_property(
            title="Departamento 2 ambientes — España",
            description=("Dos ambientes funcional, cocina integrada y balcón "
                         "corrido. Apto profesional."),
            location=self._point("espana"),
            property_type=PropertyType.APARTMENT,
            address_line="España 940, Piso 3, Dpto. A",
            city="Resistencia", neighborhood="Villa España", province="Chaco",
            area_m2=Decimal("52.00"), bedrooms=2, bathrooms=1, year_built=2015,
            features=["balcon", "cocina"],
            owner_contact_id=owner.pk, actor=actor,
        )
        # next_adjustment = start + 3m = today - 10d → days=-10 → danger.
        start_c1 = today - relativedelta(months=3, days=10)
        contract_c1 = create_rental_contract(
            property_id=prop_c1.pk, tenant_contact_id=tenant_c1.pk, owner_contact_id=owner.pk,
            start_date=start_c1, end_date=start_c1 + relativedelta(months=24),
            initial_price=Decimal("280000.00"), currency=Currency.ARS,
            payment_due_day=28, adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3, guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
            guarantee_detail="Garantía propietaria: Obligado 1200, Resistencia.",
            deposit_amount=Decimal("280000.00"), actor=actor,
        )

        # ── C2: banner WARNING (próximo) + FIXED_PERCENT ─────────────────
        prop_c2 = create_property(
            title="Local comercial — Villa Sarmiento",
            description=("Local a la calle con vidriera, baño y depósito. "
                         "Apto rubro gastronómico o comercial."),
            location=self._point("villa_sarmiento"),
            property_type=PropertyType.COMMERCIAL,
            address_line="Av. Sarmiento 2350",
            city="Resistencia", neighborhood="Villa Sarmiento", province="Chaco",
            area_m2=Decimal("65.00"), bathrooms=1, year_built=2010,
            features=["vidriera", "deposito"],
            owner_contact_id=owner.pk, actor=actor,
        )
        # next_adjustment = start + 12m = today + 18d → days=18 → warning.
        start_c2 = today - relativedelta(months=12) + relativedelta(days=18)
        contract_c2 = create_rental_contract(
            property_id=prop_c2.pk, tenant_contact_id=tenant_c2.pk, owner_contact_id=owner.pk,
            start_date=start_c2, end_date=start_c2 + relativedelta(months=36),
            initial_price=Decimal("195000.00"), currency=Currency.ARS,
            payment_due_day=28, adjustment_index=AdjustmentIndex.FIXED_PERCENT,
            adjustment_percent=Decimal("10.00"), adjustment_frequency_months=12,
            guarantee_type=GuaranteeType.BANK_GUARANTEE,
            guarantee_detail="Aval bancario — Banco del Chaco, carta 2025/0455.",
            deposit_amount=Decimal("195000.00"), actor=actor,
        )

        return {
            "owner": owner,
            "contracts": [contract_c1, contract_c2],
            "properties": [prop_c1, prop_c2],
        }

    
    def _cluster_d_venta(self, ctx):
        """
        Cluster D — Venta cerrada.

        Listing SALE en USD → deal SALE → close_deal WON → property SOLD
        (primer side-effect vía deals). Comisión split: dos COMMISSION_RECEIPT
        sobre el mismo deal, distintos pagadores (comprador y vendedor), en USD.
        El listing se cierra a mano tras la venta (close_deal no lo toca).
        Sin contrato — una venta no genera RentalContract.
        """
        self._step("Cluster D — venta cerrada (SOLD + comisión USD)")
        actor, today = ctx["actor"], ctx["today"]

        seller = create_contact(
            full_name="Eduardo Maidana", email="emaidana@example.com",
            phone="362-4800900", document_type="cuit", document_number="20284567893",
            role=ContactRole.OWNER, source=ContactSource.DIRECT, actor=actor,
        )
        buyer = create_contact(
            full_name="Carolina Ojeda", email="cojeda@example.com",
            phone="362-4900100", document_type="dni", document_number="31777888",
            role=ContactRole.INTERESTED, source=ContactSource.ZONAPROP, actor=actor,
        )

        prop = create_property(
            title="Casa 4 dormitorios — Barrio Norte",
            description=("Casa sobre lote propio, cuatro dormitorios, quincho "
                         "con parrilla y cochera doble. Lista para escriturar."),
            location=self._point("barrio_norte"),
            property_type=PropertyType.HOUSE,
            address_line="López y Planes 1560",
            city="Resistencia", neighborhood="Barrio Norte", province="Chaco",
            area_m2=Decimal("210.00"), bedrooms=4, bathrooms=2, year_built=2012,
            features=["quincho", "parrilla", "lote_propio"],
            parking_spaces=2,
            owner_contact_id=seller.pk, actor=actor,
        )

        # Listing SALE USD: DRAFT → PUBLISHED. period=TOTAL (precio de venta).
        listing = create_listing(
            property=prop, operation_type=OperationType.SALE,
            price=Decimal("120000.00"), currency=Currency.USD,
            period=PricePeriod.TOTAL, actor=actor,
        )
        self._media(prop=prop, actor=actor)
        update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)

        # Deal SALE sobre el listing → close WON → property SOLD.
        deal = create_deal(
            deal_type=DealType.SALE, client_contact_id=buyer.pk,
            listing_id=listing.pk, agent_id=actor.pk,
            expected_close_date=today - relativedelta(days=20),
            notes="Operación cerrada. Seña 10% en mano, saldo a escritura.",
            actor=actor,
        )
        close_deal(deal=deal, outcome=DealOutcome.WON, actor=actor)  # → prop.status SOLD

        # Comisión split: 3% comprador + 3% vendedor, dos recibos, un deal, USD.
        commission = (Decimal("120000.00") * Decimal("0.03")).quantize(Decimal("0.01"))  # 3600.00
        create_billing_document(
            document_type=DocumentType.COMMISSION_RECEIPT,
            lines=[ConceptLine(type=ConceptLineType.COMMISSION,
                               description="Comisión venta 3% — parte compradora",
                               amount=commission)],
            date=today, deal=deal, recipient_contact=buyer,
            currency=Currency.USD, actor=actor,
        )
        create_billing_document(
            document_type=DocumentType.COMMISSION_RECEIPT,
            lines=[ConceptLine(type=ConceptLineType.COMMISSION,
                               description="Comisión venta 3% — parte vendedora",
                               amount=commission)],
            date=today, deal=deal, recipient_contact=seller,
            currency=Currency.USD, actor=actor,
        )

        return {"seller": seller, "buyer": buyer, "property": prop, "deal": deal}


    def _cluster_e_programado(self, ctx):
        """
        Cluster E — Contrato programado.

        start_date futuro → create_rental_contract asigna SCHEDULED y NO toca
        el status de la propiedad (queda AVAILABLE). Ejercita el branch sin
        side-effect. Listing en PAUSED (reservado). Sin billing ni deal.
        """
        self._step("Cluster E — programado (SCHEDULED)")
        actor, today = ctx["actor"], ctx["today"]
        owner = ctx["a"]["owner"]  # Ricardo — 3ra propiedad, estado mixto

        tenant = create_contact(
            full_name="Federico Closs", email="fcloss@example.com",
            phone="362-4110200", document_type="dni", document_number="34555666",
            role=ContactRole.TENANT, source=ContactSource.REFERRAL, actor=actor,
        )

        prop = create_property(
            title="Departamento 1 ambiente — Güemes",
            description=("Monoambiente a estrenar, cocina americana, ideal "
                         "inversión o estudiante. Disponible desde el mes próximo."),
            location=self._point("guemes"),
            property_type=PropertyType.APARTMENT,
            address_line="Güemes 380, Piso 1, Dpto. C",
            city="Resistencia", neighborhood="Güemes", province="Chaco",
            area_m2=Decimal("38.00"), bedrooms=1, bathrooms=1, year_built=2024,
            features=["a_estrenar", "cocina"],
            owner_contact_id=owner.pk, actor=actor,
        )

        # Listing reservado: DRAFT → PUBLISHED → PAUSED (unidad ya comprometida).
        listing = create_listing(
            property=prop, operation_type=OperationType.RENT,
            price=Decimal("160000.00"), currency=Currency.ARS,
            period=PricePeriod.MONTHLY, actor=actor,
        )
        self._media(prop=prop, actor=actor)
        update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)
        update_listing_status(listing=listing, status=ListingStatus.PAUSED, actor=actor)

        # start futuro → SCHEDULED, prop.status NO cambia (sigue AVAILABLE).
        start = today + relativedelta(months=1)
        contract = create_rental_contract(
            property_id=prop.pk, tenant_contact_id=tenant.pk, owner_contact_id=owner.pk,
            start_date=start, end_date=start + relativedelta(months=24),
            initial_price=Decimal("160000.00"), currency=Currency.ARS,
            payment_due_day=10, adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3, guarantee_type=GuaranteeType.INSURANCE,
            guarantee_detail="Seguro de caución — Póliza 990321, Afianzar S.G.R.",
            deposit_amount=Decimal("160000.00"), actor=actor,
        )

        return {"owner": owner, "tenant": tenant, "property": prop, "contract": contract}

    
    def _cluster_f_ciclos(self, ctx):
        """
        Cluster F — Ciclos cerrados.

        F1 EXPIRED: contrato creado ACTIVE (start pasado, end pasado) →
            expire_contract → EXPIRED + property AVAILABLE. Sin re-listar.
        F2 TERMINATED: contrato creado ACTIVE (start pasado, end futuro) →
            terminate_contract → TERMINATED + property AVAILABLE. Re-listada
            PUBLISHED (unidad liberada y vuelta a ofrecer).
        Contraste con E: acá el side-effect de vuelta a AVAILABLE SÍ ocurre.
        Sin billing — los recibos históricos no agregan cobertura nueva.
        """
        self._step("Cluster F — ciclos cerrados (EXPIRED + TERMINATED)")
        actor, today = ctx["actor"], ctx["today"]
        owner = ctx["c"]["owner"]  # Graciela — 4 propiedades, estados mixtos

        # ── F1: EXPIRED ──────────────────────────────────────────────────
        tenant_exp = create_contact(
            full_name="Raúl Benítez", email="rbenitez@example.com",
            phone="362-4120300", document_type="dni", document_number="21333222",
            role=ContactRole.TENANT, source=ContactSource.DIRECT, actor=actor,
        )
        prop_exp = create_property(
            title="Oficina — San Fernando",
            description=("Oficina en planta alta, sobre avenida. Recepción, "
                         "dos privados y kitchenette."),
            location=self._point("san_fernando"),
            property_type=PropertyType.OFFICE,
            address_line="Av. Alvear 760, Piso 2",
            city="Resistencia", neighborhood="San Fernando", province="Chaco",
            area_m2=Decimal("48.00"), bathrooms=1, year_built=2005,
            features=["recepcion", "kitchenette"],
            owner_contact_id=owner.pk, actor=actor,
        )
        start_exp = today - relativedelta(months=14)
        contract_exp = create_rental_contract(
            property_id=prop_exp.pk, tenant_contact_id=tenant_exp.pk, owner_contact_id=owner.pk,
            start_date=start_exp, end_date=today - relativedelta(months=2),
            initial_price=Decimal("140000.00"), currency=Currency.ARS,
            payment_due_day=10, adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=6, guarantee_type=GuaranteeType.INSURANCE,
            guarantee_detail="Seguro de caución — Póliza 771209.",
            deposit_amount=Decimal("140000.00"), actor=actor,
        )
        expire_contract(contract=contract_exp, actor=actor)  # → EXPIRED + AVAILABLE

        # ── F2: TERMINATED + re-listado ──────────────────────────────────
        tenant_term = create_contact(
            full_name="Mónica Aguirre", email="maguirre@example.com",
            phone="362-4130400", document_type="dni", document_number="27888777",
            role=ContactRole.TENANT, source=ContactSource.WHATSAPP, actor=actor,
        )
        prop_term = create_property(
            title="Casa 2 dormitorios — Villa Forestación",
            description=("Casa con patio y cochera. Dos dormitorios, living "
                         "comedor con cocina integrada."),
            location=self._point("villa_forestacion"),
            property_type=PropertyType.HOUSE,
            address_line="Pellegrini 1490",
            city="Resistencia", neighborhood="Villa Forestación", province="Chaco",
            area_m2=Decimal("95.00"), bedrooms=2, bathrooms=1, year_built=2009,
            features=["patio", "cocina"],
            parking_spaces=1 ,
            owner_contact_id=owner.pk, actor=actor,
        )
        start_term = today - relativedelta(months=6)
        contract_term = create_rental_contract(
            property_id=prop_term.pk, tenant_contact_id=tenant_term.pk, owner_contact_id=owner.pk,
            start_date=start_term, end_date=start_term + relativedelta(months=24),
            initial_price=Decimal("230000.00"), currency=Currency.ARS,
            payment_due_day=5, adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=3, guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
            guarantee_detail="Garantía propietaria: Brown 220, Resistencia.",
            deposit_amount=Decimal("230000.00"), actor=actor,
        )
        terminate_contract(contract=contract_term, actor=actor)  # → TERMINATED + AVAILABLE

        # Unidad liberada → re-listada PUBLISHED sobre propiedad AVAILABLE.
        listing = create_listing(
            property=prop_term, operation_type=OperationType.RENT,
            price=Decimal("245000.00"), currency=Currency.ARS,
            period=PricePeriod.MONTHLY, actor=actor,
        )
        self._media(prop=prop_term, actor=actor)
        update_listing_status(listing=listing, status=ListingStatus.PUBLISHED, actor=actor)

        return {
            "owner": owner,
            "expired": {"contract": contract_exp, "property": prop_exp},
            "terminated": {"contract": contract_term, "property": prop_term, "listing": listing},
        }

    
    def _cluster_g_externa(self, ctx):
        """
        Cluster G — Propiedad externa + deal externo.

        G1: Property is_external=True → create_property crea la
            ExternalPropertySource (invariante mantenida solo por el service,
            sin constraint en DB). owner_contact=None: no trackeamos al dueño
            de otra agencia. Listada PUBLISHED.
        G2: Deal con external_property_notes (sin listing) → close_deal WON
            SIN side-effect (branch listing_id is None). Comisión de alquiler
            sobre ese deal → queda solo en el contacto (gap #1 del tracker).
        """
        self._step("Cluster G — externa (is_external + deal externo)")
        actor, today = ctx["actor"], ctx["today"]

        # ── G1: Propiedad externa co-publicada ───────────────────────────
        prop_ext = create_property(
            title="Departamento 2 ambientes — Villa Libertad (externa)",
            description=("Dos ambientes en pozo avanzado, co-publicado con "
                         "Inmobiliaria del Litoral. Comisión compartida."),
            location=self._point("villa_libertad"),
            property_type=PropertyType.APARTMENT,
            address_line="Av. Castelli 1820, Piso 5, Dpto. B",
            city="Resistencia", neighborhood="Villa Libertad", province="Chaco",
            area_m2=Decimal("58.00"), bedrooms=2, bathrooms=1, year_built=2023,
            features=["en_pozo", "balcon"],
            owner_contact_id=None,                       # dueño de otra agencia, sin trackear
            is_external=True,
            agency_name="Inmobiliaria del Litoral S.A.",
            source_url="https://www.zonaprop.com.ar/propiedades/ext-litoral-1820.html",
            agreed_commission_percent=Decimal("50.00"),  # 50/50 con la agencia publicante
            actor=actor,
        )
        listing_ext = create_listing(
            property=prop_ext, operation_type=OperationType.RENT,
            price=Decimal("210000.00"), currency=Currency.ARS,
            period=PricePeriod.MONTHLY, actor=actor,
        )
        self._media(prop=prop_ext, actor=actor)
        update_listing_status(listing=listing_ext, status=ListingStatus.PUBLISHED, actor=actor)

        # ── G2: Deal sobre propiedad no modelada ─────────────────────────
        client = create_contact(
            full_name="Hernán Vallejos", email="hvallejos@example.com",
            phone="362-4140500", document_type="dni", document_number="32111000",
            role=ContactRole.INTERESTED, source=ContactSource.INSTAGRAM, actor=actor,
        )
        deal_ext = create_deal(
            deal_type=DealType.RENT, client_contact_id=client.pk,
            external_property_notes=("Alquiler Dpto. Moreno 540 — propiedad de "
                                     "tercero, no listada. Cliente referido."),
            agent_id=actor.pk,
            expected_close_date=today - relativedelta(days=8),
            notes="Cerrado. Comisión de un mes a cargo del inquilino.",
            actor=actor,
        )
        close_deal(deal=deal_ext, outcome=DealOutcome.WON, actor=actor)  # SIN side-effect

        # Comisión de alquiler (deal RENT) → invisible en cobros, visible en contacto.
        create_billing_document(
            document_type=DocumentType.COMMISSION_RECEIPT,
            lines=[ConceptLine(type=ConceptLineType.COMMISSION,
                               description="Comisión alquiler — un mes (Moreno 540)",
                               amount=Decimal("210000.00"))],
            date=today, deal=deal_ext, recipient_contact=client,
            currency=Currency.ARS, actor=actor,
        )

        return {
            "external_property": prop_ext,
            "external_listing": listing_ext,
            "client": client,
            "deal": deal_ext,
        }


    def _cluster_h_pipeline(self, ctx):
        """
        Cluster H (parte 1) — Pipeline y contactos.

        - COMPANY interesada con deal ABIERTO (outcome="") → precondición de
          ContactHasOpenDeals: no se puede archivar mientras el deal siga abierto.
        - INTERESTED con dos SearchPreference (una activa, una inactiva) y un
          deal LOST.
        - Contacto con deal CANCELLED, luego ARCHIVADO (soft-delete): su único
          deal está cerrado → archive_contact no levanta el guard.
        """
        self._step("Cluster H — pipeline y contactos")
        actor, today = ctx["actor"], ctx["today"]

        # ── COMPANY con deal abierto (precondición del guard de archivado) ──
        company = create_contact(
            full_name="Constructora del Norte S.R.L.", contact_type=ContactType.COMPANY,
            email="contacto@constructoranorte.com.ar", phone="362-4150600",
            document_type="cuit", document_number="30711234560",
            role=ContactRole.INTERESTED, source=ContactSource.REFERRAL, actor=actor,
        )
        # Deal en curso sobre la unidad re-listada de F (Villa Forestación, PUBLISHED).
        create_deal(
            deal_type=DealType.RENT, client_contact_id=company.pk,
            listing_id=ctx["f"]["terminated"]["listing"].pk, agent_id=actor.pk,
            expected_close_date=today + relativedelta(days=15),
            notes="Buscan oficina/casa para sede. Visita agendada.",
            actor=actor,
        )  # outcome="" → abierto → company no archivable

        # ── INTERESTED con search prefs (activa + inactiva) y deal LOST ────
        interested = create_contact(
            full_name="Valeria Sandoval", email="vsandoval@example.com",
            phone="362-4160700", document_type="dni", document_number="33222111",
            role=ContactRole.INTERESTED, source=ContactSource.ZONAPROP, actor=actor,
        )
        SearchPreference.objects.create(
            contact=interested, operation_type=OperationType.RENT,
            price_min=Decimal("150000.00"), price_max=Decimal("250000.00"),
            currency=Currency.ARS, bedrooms_min=2,
            neighborhoods=["Centro", "Villa Sarmiento"],
            property_types=["apartment"], active=True,
        )
        SearchPreference.objects.create(
            contact=interested, operation_type=OperationType.SALE,
            price_min=Decimal("80000.00"), price_max=Decimal("130000.00"),
            currency=Currency.USD, bedrooms_min=3,
            neighborhoods=["Barrio Norte"], property_types=["house"],
            active=False,  # búsqueda pausada → no la devuelve el selector
        )
        deal_lost = create_deal(
            deal_type=DealType.RENT, client_contact_id=interested.pk,
            external_property_notes="Buscaba 2 ambientes zona Centro. No avanzó.",
            agent_id=actor.pk, actor=actor,
        )
        close_deal(deal=deal_lost, outcome=DealOutcome.LOST, actor=actor)

        # ── Contacto con deal CANCELLED → archivado ────────────────────────
        former = create_contact(
            full_name="Jorgelina Paz", email="jpaz@example.com",
            phone="362-4170800", document_type="dni", document_number="29555444",
            role=ContactRole.INTERESTED, source=ContactSource.INSTAGRAM, actor=actor,
        )
        deal_cancelled = create_deal(
            deal_type=DealType.SALE, client_contact_id=former.pk,
            external_property_notes="Interesada en local comercial. Desistió.",
            agent_id=actor.pk, actor=actor,
        )
        close_deal(deal=deal_cancelled, outcome=DealOutcome.CANCELLED, actor=actor)
        archive_contact(former, actor=actor)  # único deal cerrado → no levanta guard

        return {"company": company, "interested": interested, "archived": former}


    def _bordes_sueltos(self, ctx):
        """
        Cobertura residual que no merece historia propia:
        - Property UNAVAILABLE (estado sin camino de service — gap #6, set manual).
        - Listings en DRAFT y PENDING_APPROVAL (estados que ningún cluster dejó).
        - ListingPublication ZonaProp/ML/Facebook en PENDING/PUBLISHED/FAILED.
        - PropertyType GARAGE y LAND.
        """
        self._step("Bordes sueltos — estados residuales")
        actor, today = ctx["actor"], ctx["today"]
        ricardo = ctx["a"]["owner"]
        graciela = ctx["c"]["owner"]

        # ── Property UNAVAILABLE (gap #6: no hay service de transición) ────
        prop_unavail = create_property(
            title="Cochera — Villa Chica",
            description="Cochera cubierta, retirada del mercado por refacción.",
            location=self._point("villa_chica"),
            property_type=PropertyType.GARAGE,
            address_line="Saavedra 410, Cochera 12",
            city="Resistencia", neighborhood="Villa Chica", province="Chaco",
            area_m2=Decimal("15.00"),
            owner_contact_id=ricardo.pk, actor=actor,
        )
        withdraw_property(property=prop_unavail, actor=actor)
        # camino con service: withdraw_property (AVAILABLE → UNAVAILABLE),
        # que reconcilia listings vía el orquestador. Cierra el gap #6.

        # ── Listing DRAFT sobre la oficina expirada de F (AVAILABLE) ──────
        # La agencia empieza a re-listar la unidad vencida; aún sin publicar.
        create_listing(
            property=ctx["f"]["expired"]["property"],
            operation_type=OperationType.RENT,
            price=Decimal("150000.00"), currency=Currency.ARS,
            period=PricePeriod.MONTHLY, actor=actor,
        )  # status DRAFT por defecto, no se publica

        # ── Listing PENDING_APPROVAL sobre un terreno nuevo (LAND/venta) ──
        prop_land = create_property(
            title="Terreno 600 m² — Ejido Norte",
            description="Lote en zona de expansión, servicios en la traza. Apto construir.",
            location=self._point("ejido_norte"),
            property_type=PropertyType.LAND,
            address_line="Ruta 16 km 8, Lote 14",
            city="Resistencia", neighborhood="Ejido Norte", province="Chaco",
            area_m2=Decimal("600.00"),
            owner_contact_id=graciela.pk, actor=actor,
        )
        listing_land = create_listing(
            property=prop_land, operation_type=OperationType.SALE,
            price=Decimal("45000.00"), currency=Currency.USD,
            period=PricePeriod.TOTAL, actor=actor,
        )
        update_listing_status(
            listing=listing_land, status=ListingStatus.PENDING_APPROVAL, actor=actor,
        )

        # ── ListingPublication en 3 canales/estados sobre el listing PUBLISHED de F2 ──
        listing_pub = ctx["f"]["terminated"]["listing"]
        # ZonaProp → sincronizado OK
        pub_zp = create_listing_publication(
            listing=listing_pub, channel=PublicationChannel.ZONAPROP, actor=actor,
        )
        update_publication_status(
            publication=pub_zp, status=PublicationStatus.PUBLISHED,
            external_id="ZP-48821190", metadata={"avisos": 1}, actor=actor,
        )
        # MercadoLibre → falló la sincronización
        pub_ml = create_listing_publication(
            listing=listing_pub, channel=PublicationChannel.MERCADOLIBRE, actor=actor,
        )
        update_publication_status(
            publication=pub_ml, status=PublicationStatus.FAILED,
            metadata={"error": "categoría inválida"}, actor=actor,
        )
        # Facebook → recién encolado, queda PENDING
        create_listing_publication(
            listing=listing_pub, channel=PublicationChannel.FACEBOOK, actor=actor,
        )


    def _cluster_consolidacion(self, ctx):
        """
        Consolidación — Rendición de cuentas multi-contrato (demo).

        Propietario dedicado con DOS unidades alquiladas y al día este período
        (ambas con su RENT_RECEIPT → PAID). La rendición consolida los dos
        contratos en un único OWNER_STATEMENT, con contract_id por renglón.

        Ejercita el sign map completo del statement:
          RENT (+), COMMISSION (−), OTHER_CHARGE (−), OTHER_CREDIT (+)
        y la consolidación real de varios contract_id en un mismo documento.
        """
        self._step("Consolidación — rendición multi-contrato")
        actor, today, period = ctx["actor"], ctx["today"], ctx["period"]

        owner = create_contact(
            full_name="Beatriz Lezcano", email="blezcano@example.com",
            phone="362-4180900", document_type="cuit", document_number="27205678904",
            role=ContactRole.OWNER, source=ContactSource.REFERRAL, actor=actor,
        )
        tenant_1 = create_contact(
            full_name="Gonzalo Ferreyra", email="gferreyra@example.com",
            phone="362-4190100", document_type="dni", document_number="34111555",
            role=ContactRole.TENANT, source=ContactSource.ZONAPROP, actor=actor,
        )
        tenant_2 = create_contact(
            full_name="Daniela Ortiz", email="dortiz@example.com",
            phone="362-4200200", document_type="dni", document_number="35222666",
            role=ContactRole.TENANT, source=ContactSource.WHATSAPP, actor=actor,
        )

        # ── Dos unidades de Beatriz, ambas RENTED y al día ────────────────
        prop_1 = create_property(
            title="Departamento 2 ambientes — Centro",
            description="Dos ambientes sobre avenida, luminoso. En administración.",
            location=self._point("centro"),
            property_type=PropertyType.APARTMENT,
            address_line="Av. 9 de Julio 540, Piso 6, Dpto. A",
            city="Resistencia", neighborhood="Centro", province="Chaco",
            area_m2=Decimal("54.00"), bedrooms=2, bathrooms=1, year_built=2016,
            features=["balcon"], owner_contact_id=owner.pk, actor=actor,
        )
        prop_2 = create_property(
            title="Departamento 1 ambiente — Güemes",
            description="Monoambiente funcional, en administración.",
            location=self._point("guemes"),
            property_type=PropertyType.APARTMENT,
            address_line="Güemes 1120, Piso 2, Dpto. D",
            city="Resistencia", neighborhood="Güemes", province="Chaco",
            area_m2=Decimal("36.00"), bedrooms=1, bathrooms=1, year_built=2019,
            features=["amoblado"], owner_contact_id=owner.pk, actor=actor,
        )

        start = today - relativedelta(months=8)
        contract_1 = create_rental_contract(
            property_id=prop_1.pk, tenant_contact_id=tenant_1.pk, owner_contact_id=owner.pk,
            start_date=start, end_date=start + relativedelta(months=24),
            initial_price=Decimal("260000.00"), currency=Currency.ARS,
            payment_due_day=10, adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=6, guarantee_type=GuaranteeType.PROPERTY_GUARANTEE,
            guarantee_detail="Garantía propietaria: Yrigoyen 330, Resistencia.",
            deposit_amount=Decimal("260000.00"), actor=actor,
        )
        contract_2 = create_rental_contract(
            property_id=prop_2.pk, tenant_contact_id=tenant_2.pk, owner_contact_id=owner.pk,
            start_date=start, end_date=start + relativedelta(months=24),
            initial_price=Decimal("175000.00"), currency=Currency.ARS,
            payment_due_day=10, adjustment_index=AdjustmentIndex.ICL,
            adjustment_frequency_months=6, guarantee_type=GuaranteeType.INSURANCE,
            guarantee_detail="Seguro de caución — Póliza 660145.",
            deposit_amount=Decimal("175000.00"), actor=actor,
        )

        # Recibos del período → ambos contratos PAID.
        for contract in (contract_1, contract_2):
            create_billing_document(
                document_type=DocumentType.RENT_RECEIPT,
                lines=[ConceptLine(type=ConceptLineType.RENT,
                                   description=f"Alquiler {period:%m/%Y}",
                                   amount=contract.current_price)],
                date=today, period=period, contract=contract, actor=actor,
            )

        # ── Rendición consolidada: los dos contratos en un solo documento ──
        com_1 = (contract_1.current_price * Decimal("0.10")).quantize(Decimal("0.01"))
        com_2 = (contract_2.current_price * Decimal("0.10")).quantize(Decimal("0.01"))
        create_billing_document(
            document_type=DocumentType.OWNER_STATEMENT,
            lines=[
                # Unidad 1: alquiler cobrado − comisión 10%
                ConceptLine(type=ConceptLineType.RENT,
                            description="Alquiler 9 de Julio 540 — período actual",
                            amount=contract_1.current_price, contract_id=str(contract_1.pk)),
                ConceptLine(type=ConceptLineType.COMMISSION,
                            description="Comisión administración 9 de Julio 540",
                            amount=com_1, contract_id=str(contract_1.pk)),
                # Unidad 2: alquiler cobrado − comisión 10%
                ConceptLine(type=ConceptLineType.RENT,
                            description="Alquiler Güemes 1120 — período actual",
                            amount=contract_2.current_price, contract_id=str(contract_2.pk)),
                ConceptLine(type=ConceptLineType.COMMISSION,
                            description="Comisión administración Güemes 1120",
                            amount=com_2, contract_id=str(contract_2.pk)),
                # Cargos/haberes de la agencia (exentos de contract_id)
                ConceptLine(type=ConceptLineType.OTHER_CHARGE,
                            description="Gasto de plomería abonado por la agencia (9 de Julio 540)",
                            amount=Decimal("18000.00")),
                ConceptLine(type=ConceptLineType.OTHER_CREDIT,
                            description="Reintegro retención mal aplicada mes anterior",
                            amount=Decimal("5000.00")),
            ],
            date=today, period=period, recipient_contact=owner, actor=actor,
        )

        return {"owner": owner, "contracts": [contract_1, contract_2]}