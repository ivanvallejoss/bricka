from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0006_issued_rent_unique"),  
    ]

    operations = [
        migrations.AddConstraint(
            model_name="billingdocument",
            constraint=models.UniqueConstraint(
                fields=["contract", "period"],
                condition=Q(document_type="expense_receipt", status="issued"),
                name="unique_issued_expense_receipt_per_period",
            ),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="recipient_name",
            field=models.CharField(max_length=255, default=""),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="recipient_document_type",
            field=models.CharField(max_length=20, default="", blank=True),
        ),
        migrations.AddField(
            model_name="billingdocument",
            name="recipient_document_number",
            field=models.CharField(max_length=50, default="", blank=True),
        ),
    ]