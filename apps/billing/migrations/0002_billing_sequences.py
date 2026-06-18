from django.db import migrations


class Migration(migrations.Migration):
    """
    Crea sequences de PostgreSQL para numeración correlativa
    por tipo de comprobante.

    Trade-off documentado: gaps posibles si una transacción hace
    rollback después de consumir nextval(). Aceptable para V1.
    Incompatible con numeración AFIP — revisar cuando se active
    integración fiscal.
    """
    dependencies = [
        ("billing", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE SEQUENCE IF NOT EXISTS billing_rent_receipt_seq;
                CREATE SEQUENCE IF NOT EXISTS billing_commission_receipt_seq;
                CREATE SEQUENCE IF NOT EXISTS billing_expense_receipt_seq;
            """,
            reverse_sql="""
                DROP SEQUENCE IF EXISTS billing_rent_receipt_seq;
                DROP SEQUENCE IF EXISTS billing_commission_receipt_seq;
                DROP SEQUENCE IF EXISTS billing_expense_receipt_seq;
            """,
        ),
    ]