"""Tests du repli LongName → Name (donnée présente mais au mauvais endroit).

Certains outils auteurs (ArchiCAD notamment) remplissent ``Name`` là où le
CCH attend ``LongName``. Le repli doit :

- retrouver la valeur (l'exigence de contenu est satisfaite) ;
- signaler le mauvais emplacement en LOW au lieu du HIGH « manquant ».
"""

from __future__ import annotations

from audit_bim.audit.findings import ErrorType, Severity
from audit_bim.audit.rules.naming import audit_naming
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.extraction.normalizer import (
    get_attribute_with_fallback,
    get_quantity_with_fallback,
    resolve_value,
)
from audit_bim.requirements.models import RequirementsCatalog


def _space(uuid: str, name: str | None, longname: str | None) -> dict:
    return {"uuid": uuid, "type": "IfcSpace", "name": name, "longname": longname}


def _snapshot(spaces: list[dict]) -> ModelSnapshot:
    snap = ModelSnapshot(spaces=spaces, elements=list(spaces))
    snap.elements_by_type = {"IfcSpace": spaces}
    snap.element_by_uuid = {s["uuid"]: s for s in spaces}
    return snap


# ── normalizer ───────────────────────────────────────────────────────────────


def test_get_attribute_with_fallback_prefere_longname():
    el = _space("a", name="CH1", longname="CHAMBRE 01")
    assert get_attribute_with_fallback(el, "LongName") == "CHAMBRE 01"


def test_get_attribute_with_fallback_replie_sur_name():
    el = _space("a", name="CHAMBRE 01", longname=None)
    assert get_attribute_with_fallback(el, "LongName") == "CHAMBRE 01"
    value, source = get_attribute_with_fallback(el, "LongName", report_source=True)
    assert (value, source) == ("CHAMBRE 01", "name")


def test_get_attribute_with_fallback_rien():
    el = _space("a", name=None, longname=None)
    assert get_attribute_with_fallback(el, "LongName") is None
    assert get_attribute_with_fallback(el, "LongName", report_source=True) == (None, None)


def test_resolve_value_longname_fallback():
    el = _space("a", name="SEJOUR", longname=None)
    assert resolve_value(el, "LongName", "Nom 3F de la Pièce") == "SEJOUR"


def test_resolve_value_name_sans_repli_inverse():
    """Le repli est asymétrique : Name vide ne va pas chercher LongName."""
    el = _space("a", name=None, longname="SEJOUR")
    assert resolve_value(el, "Name", "Nom de l'objet") is None


# ── repli quantités ArchiCAD (Surface mesurée) ───────────────────────────────


def _space_with_psets(uuid: str, psets: list[dict]) -> dict:
    return {
        "uuid": uuid,
        "type": "IfcSpace",
        "name": "SEJOUR",
        "longname": None,
        "property_sets": psets,
    }


def _pset(name: str, props: dict) -> dict:
    return {
        "name": name,
        "properties": [{"definition": {"name": k}, "value": v} for k, v in props.items()],
    }


def test_quantity_fallback_surface_mesuree():
    """BaseQuantities absent → repli sur AC_Pset_Marque_de_zone."""
    el = _space_with_psets(
        "q1",
        [
            _pset("AC_Pset_Marque_de_zone_02_25", {"Surface mesurée": 12.5}),
        ],
    )
    assert get_quantity_with_fallback(el, "BaseQuantities", "NetFloorArea") == 12.5
    # resolve_value passe par le même repli sur un chemin composite
    assert resolve_value(el, "BaseQuantities/NetArea", "Surface") == 12.5


def test_quantity_fallback_superficie_calculee():
    """ArchiCAD nomme parfois la surface 'Superficie …' et non 'Surface …' :
    régression du faux 'surface manquante' en audit CCH 2026."""
    el = _space_with_psets(
        "q_sup",
        [
            _pset("AC_Pset_Marque_de_zone_02_25", {"Superficie calculée": 12.98}),
        ],
    )
    assert get_quantity_with_fallback(el, "BaseQuantities", "NetFloorArea") == 12.98


def test_quantity_fallback_priorite_basequantities():
    """Les BaseQuantities restent prioritaires quand elles existent."""
    el = _space_with_psets(
        "q2",
        [
            _pset("BaseQuantities", {"NetFloorArea": 14.2}),
            _pset("AC_Pset_Marque_de_zone_02_25", {"Surface mesurée": 12.5}),
        ],
    )
    assert get_quantity_with_fallback(el, "BaseQuantities", "NetFloorArea") == 14.2


def test_quantity_fallback_seulement_pour_les_surfaces():
    """Pas de repli pour les quantités non surfaciques (Height…)."""
    el = _space_with_psets(
        "q3",
        [
            _pset("AC_Pset_Marque_de_zone_02_25", {"Surface mesurée": 12.5}),
        ],
    )
    assert get_quantity_with_fallback(el, "BaseQuantities", "Height") is None


# ── règle de nommage pièces ──────────────────────────────────────────────────


def _findings_for(spaces):
    snap = _snapshot(spaces)
    catalog = RequirementsCatalog()
    return audit_naming(snap, catalog)


def test_naming_longname_vide_mais_name_rempli_donne_low():
    findings = _findings_for([_space("s1", name="CHAMBRE 01", longname=None)])
    space_findings = [f for f in findings if f.element_uuid == "s1"]
    assert len(space_findings) == 1
    f = space_findings[0]
    assert f.severity == Severity.LOW
    assert f.error_type == ErrorType.NAMING_INVALID_FORMAT
    assert "Name" in str(f.actual)


def test_naming_tout_vide_reste_high_missing():
    findings = _findings_for([_space("s2", name=None, longname=None)])
    space_findings = [f for f in findings if f.element_uuid == "s2"]
    assert len(space_findings) == 1
    assert space_findings[0].severity == Severity.HIGH
    assert space_findings[0].error_type == ErrorType.NAMING_MISSING


def test_naming_longname_rempli_pas_de_finding_emplacement():
    findings = _findings_for([_space("s3", name="001", longname="CHAMBRE 01")])
    assert not [
        f
        for f in findings
        if f.element_uuid == "s3" and "emplacement" in str(f.recommended_action or "").lower()
    ]
