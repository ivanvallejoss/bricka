from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0010_seed_feature_vocabulary"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="propertymedia",
            options={
                "ordering": ["order", "created_at"],
                "verbose_name": "archivo multimedia",
                "verbose_name_plural": "archivos multimedia",
            },
        ),
    ]