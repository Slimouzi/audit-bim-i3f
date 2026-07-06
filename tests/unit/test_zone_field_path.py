"""Verrou : classification Name/ObjectType des zones via ``field_path`` structuré.

La grille de contrôle AVP distingue « Zones Nommage » (Name) et « Zones
ObjectType ». Avant, ``_zone_finding_kind`` discriminait en cherchant le mot
« objecttype » dans le **libellé** du finding — un reformulage de
``rules/naming.py`` aurait faussé silencieusement la grille. On s'appuie désormais
sur le champ **neutre** ``field_path`` (bim-core ≥ 0.1.1) :

- **émission** obligatoire de ``field_path`` sur les 4 sites zone de ``naming.py`` ;
- **consommation** prioritaire dans ``_zone_finding_kind`` ;
- **anti-wording** : le classement suit ``field_path``, pas le libellé ;
- **repli** heuristique conservé pour les findings sans ``field_path``.
"""

from __future__ import annotations

from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.audit.rules import audit_naming
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.reporting.avp_i3f import _zone_finding_kind
from audit_bim.requirements.models import NamingRule, RequirementsCatalog, ZoneSpec


def _catalog() -> RequirementsCatalog:
    return RequirementsCatalog(
        cch_version="3.6",
        cch_source_pdf="x",
        data_spec_source="x",
        naming_spec_source="x",
        properties=[],
        naming_rules=[
            NamingRule(
                objet="Zone logement",
                ifc_class="IfcZone",
                ifc_attribute="Name",
                pattern=r"\d{4}L-\d{4}",
            )
        ],
        storey_names=[],
        zone_specs=[ZoneSpec(name="Logement T2", type_label="Zone Logement T2")],
        room_specs=[],
    )


def _zone_findings(name, object_type):
    zone = {"uuid": "Z1", "type": "IfcZone", "name": name, "object_type": object_type}
    snap = ModelSnapshot(project={"name": "P"}, model={"name": "M.ifc"}, zones=[zone]).index()
    return [f for f in audit_naming(snap, _catalog()) if f.ifc_type == "IfcZone"]


def _paths(findings):
    return {f.error_type: f.field_path for f in findings}


# ── Émission de field_path (4 sites zone) ─────────────────────────────────


def test_emit_field_path_name_missing():
    fs = _zone_findings(None, "Zone Logement T2")  # Name absent, OT valide
    paths = _paths(fs)
    assert paths[ErrorType.NAMING_MISSING] == "IfcZone.Name"


def test_emit_field_path_name_invalid_format():
    fs = _zone_findings("BADNAME", "Zone Logement T2")  # dwelling, mauvais pattern
    paths = _paths(fs)
    assert paths[ErrorType.NAMING_INVALID_FORMAT] == "IfcZone.Name"


def test_emit_field_path_objecttype_missing():
    fs = _zone_findings("1802L-1101", None)  # Name ok, OT absent
    paths = _paths(fs)
    assert paths[ErrorType.NAMING_MISSING] == "IfcZone.ObjectType"


def test_emit_field_path_objecttype_not_in_list():
    fs = _zone_findings("1802L-1101", "Zone Bidon")  # OT hors liste (non-dwelling)
    paths = _paths(fs)
    assert paths[ErrorType.NAMING_NOT_IN_LIST] == "IfcZone.ObjectType"


# ── Consommation : field_path prioritaire, anti-wording ───────────────────


def _zone_finding(*, field_path, recommended_action, error_type=ErrorType.NAMING_MISSING):
    return Finding(
        theme=Theme.NAMING_ZONE,
        severity=Severity.HIGH,
        error_type=error_type,
        ifc_type="IfcZone",
        element_uuid="Z1",
        field_path=field_path,
        recommended_action=recommended_action,
    )


def test_kind_follows_field_path_over_misleading_name_wording():
    # field_path dit ObjectType mais le libellé parle de « Name » → ObjectType gagne.
    f = _zone_finding(
        field_path="IfcZone.ObjectType", recommended_action="Renseigner IfcZone/Name."
    )
    assert _zone_finding_kind(f) == "objecttype"


def test_kind_follows_field_path_over_misleading_objecttype_wording():
    # field_path dit Name mais le libellé parle d'« ObjectType » → Name gagne.
    f = _zone_finding(
        field_path="IfcZone.Name",
        recommended_action="Aligner le ObjectType de la zone…",
        error_type=ErrorType.NAMING_INVALID_FORMAT,
    )
    assert _zone_finding_kind(f) == "name"


def test_kind_falls_back_to_wording_without_field_path():
    # Sans field_path (finding historique) : repli heuristique.
    f_ot = _zone_finding(
        field_path=None,
        recommended_action="Aligner le ObjectType…",
        error_type=ErrorType.NAMING_NOT_IN_LIST,
    )
    assert _zone_finding_kind(f_ot) == "objecttype"
    f_name = _zone_finding(field_path=None, recommended_action="Renseigner IfcZone/Name.")
    assert _zone_finding_kind(f_name) == "name"


def test_real_findings_classified_via_field_path():
    # Bout-en-bout : les vrais findings d'audit_naming se classent correctement.
    name_missing = _zone_findings(None, "Zone Logement T2")
    assert all(_zone_finding_kind(f) == "name" for f in name_missing)
    ot_missing = _zone_findings("1802L-1101", None)
    assert all(_zone_finding_kind(f) == "objecttype" for f in ot_missing)
