from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0005_owner_statement_sequence"), 
    ]

    operations = [
        migrations.AddConstraint(
            model_name="billingdocument",
            constraint=models.UniqueConstraint(
                fields=["contract", "period"],
                condition=Q(
                    document_type="rent_receipt",
                    status="issued",
                ),
                name="unique_issued_rent_receipt_per_period",
            ),
        ),
    ]