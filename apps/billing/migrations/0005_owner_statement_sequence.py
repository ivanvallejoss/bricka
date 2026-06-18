from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("billing", "0004_billing_document_restructure"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE SEQUENCE billing_owner_statement_seq;",
            reverse_sql="DROP SEQUENCE billing_owner_statement_seq;",
        ),
    ]