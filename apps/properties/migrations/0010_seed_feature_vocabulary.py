from django.db import migrations

# Vocabulario v1 — (category, slug, label).
# Fuente: lista del dueño del producto (jul 2026) + slugs del seed que
# pasaron el criterio de la Decisión 2 ("¿presencia o número?").
# El afinado posterior de labels vive en el admin; los slugs no se renombran.
VOCABULARY_V1 = [
    # Características generales
    ("general", "acceso_discapacitados", "Acceso para personas discapacitadas"),
    ("general", "parrilla", "Parrilla"),
    ("general", "solarium", "Solárium"),
    ("general", "apto_profesional", "Apto profesional"),
    ("general", "permite_mascotas", "Permite mascotas"),
    ("general", "uso_comercial", "Uso comercial"),
    ("general", "gimnasio", "Gimnasio"),
    ("general", "pileta", "Pileta"),
    ("general", "hidromasaje", "Hidromasaje"),
    ("general", "sala_de_juegos", "Sala de juegos"),
    ("general", "lote_propio", "Lote propio"),
    ("general", "a_estrenar", "A estrenar"),
    ("general", "en_pozo", "En pozo"),
    # Características
    ("caracteristicas", "aire_acondicionado", "Aire acondicionado"),
    ("caracteristicas", "cocina_equipada", "Cocina equipada"),
    ("caracteristicas", "sum", "SUM"),
    ("caracteristicas", "alarma", "Alarma"),
    ("caracteristicas", "frigobar", "Frigobar"),
    ("caracteristicas", "sauna", "Sauna"),
    ("caracteristicas", "amoblado", "Amoblado"),
    ("caracteristicas", "lavarropas", "Lavarropas"),
    ("caracteristicas", "secarropas", "Secarropas"),
    ("caracteristicas", "lavavajillas", "Lavavajillas"),
    ("caracteristicas", "termotanque", "Termotanque"),
    ("caracteristicas", "calefaccion", "Calefacción"),
    ("caracteristicas", "microondas", "Microondas"),
    ("caracteristicas", "canchas_deporte", "Canchas de deporte"),
    ("caracteristicas", "quincho", "Quincho"),
    ("caracteristicas", "vidriera", "Vidriera"),
    # Servicios
    ("servicios", "ascensor", "Ascensor"),
    ("servicios", "caja_fuerte", "Caja fuerte"),
    ("servicios", "encargado", "Encargado"),
    ("servicios", "limpieza", "Limpieza"),
    # Ambientes
    ("ambientes", "balcon", "Balcón"),
    ("ambientes", "baulera", "Baulera"),
    ("ambientes", "cocina", "Cocina"),
    ("ambientes", "comedor", "Comedor"),
    ("ambientes", "comedor_diario", "Comedor diario"),
    ("ambientes", "dependencia_servicio", "Dependencia de servicio"),
    ("ambientes", "dormitorio_suite", "Dormitorio en suite"),
    ("ambientes", "escritorio", "Escritorio"),
    ("ambientes", "hall", "Hall"),
    ("ambientes", "jardin", "Jardín"),
    ("ambientes", "lavadero", "Lavadero"),
    ("ambientes", "living", "Living"),
    ("ambientes", "living_comedor", "Living comedor"),
    ("ambientes", "patio", "Patio"),
    ("ambientes", "sotano", "Sótano"),
    ("ambientes", "terraza", "Terraza"),
    ("ambientes", "vestidor", "Vestidor"),
    ("ambientes", "deposito", "Depósito"),
    ("ambientes", "recepcion", "Recepción"),
    ("ambientes", "kitchenette", "Kitchenette"),
]


def seed_vocabulary(apps, schema_editor):
    Feature = apps.get_model("properties", "Feature")
    Feature.objects.bulk_create(
        Feature(slug=slug, label=label, category=category)
        for category, slug, label in VOCABULARY_V1
    )


def unseed_vocabulary(apps, schema_editor):
    Feature = apps.get_model("properties", "Feature")
    Feature.objects.filter(
        slug__in=[slug for _, slug, _ in VOCABULARY_V1]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0009_feature_category"),
    ]

    operations = [
        migrations.RunPython(seed_vocabulary, unseed_vocabulary),
    ]