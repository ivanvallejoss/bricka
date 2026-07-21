from django.urls import reverse

from apps.listings.services import MIN_DESCRIPTION_LENGTH, MIN_PHOTOS_TO_PUBLISH
from apps.properties.checklist import (
    FLOW_EDIT,
    FLOW_WIZARD,
    build_publication_checklist,
)
from .factories import PropertyFactory, PropertyMediaFactory


class TestBuildPublicationChecklist:
    def test_photos_item_wizard_flow(self, db):
        prop = PropertyFactory()
        PropertyMediaFactory.create_batch(3, property=prop)
        [item] = build_publication_checklist(prop, ["photos"], FLOW_WIZARD)
        assert item.code == "photos"
        assert item.label == "Fotos"
        assert item.detail == f"3 de {MIN_PHOTOS_TO_PUBLISH} mínimas"
        assert item.link_url == reverse("properties:new_fotos", args=[prop.pk])
        assert item.link_text == "Ir a Fotos"

    def test_photos_item_edit_flow_links_to_anchor(self, db):
        prop = PropertyFactory()
        [item] = build_publication_checklist(prop, ["photos"], FLOW_EDIT)
        assert item.link_url == reverse("properties:edit", args=[prop.pk]) + "#fotos"

    def test_description_item_wizard_flow(self, db):
        prop = PropertyFactory(description="Corto")
        [item] = build_publication_checklist(prop, ["description"], FLOW_WIZARD)
        assert item.code == "description"
        assert item.label == "Descripción"
        assert item.detail == f"5/{MIN_DESCRIPTION_LENGTH} caracteres"
        assert item.link_url == reverse("properties:new_detalle", args=[prop.pk])
        assert item.link_text == "Ir a Detalle"

    def test_description_item_edit_flow_links_to_anchor(self, db):
        prop = PropertyFactory(description="Corto")
        [item] = build_publication_checklist(prop, ["description"], FLOW_EDIT)
        assert item.link_url == reverse("properties:edit", args=[prop.pk]) + "#detalle"

    def test_detail_reflects_live_counts(self, db):
        prop = PropertyFactory(description="x" * 40)
        PropertyMediaFactory.create_batch(2, property=prop)
        items = build_publication_checklist(prop, ["photos", "description"], FLOW_EDIT)
        by_code = {i.code: i for i in items}
        assert by_code["photos"].detail == f"2 de {MIN_PHOTOS_TO_PUBLISH} mínimas"
        assert by_code["description"].detail == f"40/{MIN_DESCRIPTION_LENGTH} caracteres"

    def test_canonical_order_photos_before_description(self, db):
        prop = PropertyFactory(description="Corto")
        # el gate append-ea description antes que photos; el checklist reordena.
        items = build_publication_checklist(prop, ["description", "photos"], FLOW_EDIT)
        assert [i.code for i in items] == ["photos", "description"]

    def test_only_missing_codes_are_included(self, db):
        prop = PropertyFactory()
        items = build_publication_checklist(prop, ["photos"], FLOW_EDIT)
        assert [i.code for i in items] == ["photos"]

    def test_unknown_code_degrades_without_link(self, db):
        prop = PropertyFactory()
        [item] = build_publication_checklist(prop, ["location"], FLOW_EDIT)
        assert item.code == "location"
        assert item.link_url is None
        assert item.link_text is None

    def test_empty_missing_returns_empty(self, db):
        prop = PropertyFactory()
        assert build_publication_checklist(prop, [], FLOW_EDIT) == []