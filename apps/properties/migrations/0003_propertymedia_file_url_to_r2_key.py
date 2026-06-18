from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0002_rename_property_id_externalpropertysource_property_and_more"),  # ← tu última migración
    ]

    operations = [
        migrations.RenameField(
            model_name="propertymedia",
            old_name="file_url",
            new_name="r2_key",
        ),
        migrations.AlterField(
            model_name="propertymedia",
            name="r2_key",
            field=models.CharField(max_length=500, unique=True),
        ),
    ]