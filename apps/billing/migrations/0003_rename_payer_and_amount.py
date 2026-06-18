from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0002_billing_sequences"), 
    ]

    operations = [
        migrations.RenameField(
            model_name="billingdocument",
            old_name="payer_contact",
            new_name="recipient_contact",
        ),
        migrations.RenameField(
            model_name="billingdocument",
            old_name="amount",
            new_name="total_amount",
        ),
    ]