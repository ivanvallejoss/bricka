from django.db import migrations
import uuid


def create_default_stages(apps, schema_editor):
    PipelineStage = apps.get_model("deals", "PipelineStage")
    PipelineStage.objects.get_or_create(
        pipeline_type="sale",
        defaults={
            "id": uuid.uuid4(),
            "name": "En negociación",
            "order": 1,
            "is_terminal_won": False,
            "is_terminal_lost": False,
        },
    )
    PipelineStage.objects.get_or_create(
        pipeline_type="rent",
        defaults={
            "id": uuid.uuid4(),
            "name": "En negociación",
            "order": 1,
            "is_terminal_won": False,
            "is_terminal_lost": False,
        },
    )


def delete_default_stages(apps, schema_editor):
    PipelineStage = apps.get_model("deals", "PipelineStage")
    PipelineStage.objects.filter(name="En negociación").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("deals", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_default_stages,
            reverse_code=delete_default_stages,
        ),
    ]