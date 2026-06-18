import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0003_rename_payer_and_amount"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="billingdocument",
            name="billing_document_requires_deal_or_contract",
        ),
        migrations.AlterField(
            model_name="billingdocument",
            name="concept",
            field=models.JSONField(default=list),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="period",
            field=models.DateField(null=True, blank=True),
        ),
        migrations.AlterField(
            model_name="billingdocument",
            name="document_type",
            field=models.CharField(
                max_length=30,
                choices=[
                    ("rent_receipt", "Recibo de alquiler"),
                    ("commission_receipt", "Recibo de comisión"),
                    ("expense_receipt", "Recibo de gasto"),
                    ("owner_statement", "Rendición de cuentas"),
                ],
            ),
        ),
        migrations.AddIndex(
            model_name="billingdocument",
            index=models.Index(
                fields=["contract", "document_type", "period"],
                name="billing_badge_lookup_idx",
            ),
        ),
    ]