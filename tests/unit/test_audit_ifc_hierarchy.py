"""Tests du module ``audit_bim.audit.ifc_hierarchy``."""
from __future__ import annotations

from audit_bim.audit.ifc_hierarchy import IFC_SUBCLASSES, expand_class, normalize_catalog_class


class TestExpandClass:
    def test_wall_includes_standard_case(self):
        result = expand_class("IfcWall")
        assert "IfcWall" in result
        assert "IfcWallStandardCase" in result

    def test_unknown_class_returns_itself(self):
        assert expand_class("IfcUnknown") == ["IfcUnknown"]

    def test_parent_always_first(self):
        for parent in IFC_SUBCLASSES.keys():
            assert expand_class(parent)[0] == parent

    def test_slab_includes_standard_case(self):
        assert "IfcSlabStandardCase" in expand_class("IfcSlab")


class TestNormalizeCatalogClass:
    def test_single_class_passthrough(self):
        assert normalize_catalog_class("IfcWall") == ["IfcWall"]

    def test_newline_separated_classes_split(self):
        result = normalize_catalog_class("IfcDuctFittingType\nIfcDuctSegmentType")
        assert "IfcDuctFittingType" in result
        assert "IfcDuctSegmentType" in result

    def test_underscore_suffix_stripped(self):
        # IfcCovering_CEILING → IfcCovering
        result = normalize_catalog_class("IfcCovering_CEILING")
        assert result == ["IfcCovering"]

    def test_lowercase_ifc_normalized(self):
        assert normalize_catalog_class("ifcSlab") == ["IfcSlab"]

    def test_a_defaut_fallback_extracted(self):
        result = normalize_catalog_class(
            "IfcTendon\nà défaut IfcBuildingElementProxy"
        )
        assert "IfcTendon" in result
        # Le fallback aussi (ordre non garanti)
        assert "IfcBuildingElementProxy" in result

    def test_empty_input(self):
        assert normalize_catalog_class("") == []
        assert normalize_catalog_class(None) == []

    def test_non_ifc_string_ignored(self):
        assert normalize_catalog_class("Documents") == []

    def test_dedup_preserves_order(self):
        result = normalize_catalog_class("IfcWall\nIfcWall\nIfcSlab")
        assert result == ["IfcWall", "IfcSlab"]
