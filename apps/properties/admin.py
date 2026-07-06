from django.contrib import admin

from .models import Feature


@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("slug", "label", "is_active")
    list_editable = ("label", "is_active")
    search_fields = ("slug", "label")