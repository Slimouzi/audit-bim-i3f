"""Medium (audit profond 2ᵉ passe) — la règle de nommage ``IfcProject/LongName``
s'applique au **LongName de l'IfcProject de l'IFC** (racine de ``structure_tree``),
et non au nom du **projet plateforme** BIMData (``snap.project``, saisi dans l'UI).
"""

from __future__ import annotations

from audit_bim.audit.findings import ErrorType
from audit_bim.audit.rules.naming import audit_naming
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import NamingRule, RequirementsCatalog


def _catalog(max_length: int = 10) -> RequirementsCatalog:
    return RequirementsCatalog(
        naming_rules=[
            NamingRule(
                objet="Projet",
                ifc_class="IfcProject",
                ifc_attribute="LongName",
                max_length=max_length,
                ref_cch="Chap 6.3.1",
            )
        ]
    )


def _snap(*, platform_name: str, tree: list) -> ModelSnapshot:
    return ModelSnapshot(
        project={"name": platform_name},
        model={"name": "M.ifc"},
        sites=[],
        buildings=[],
        storeys=[],
        spaces=[],
        zones=[],
        elements=[],
        structure_tree=tree,
    ).index()


def _project_findings(snap, cat):
    return [f for f in audit_naming(snap, cat) if f.ifc_type == "IfcProject"]


def test_too_long_ifc_project_longname_is_flagged():
    tree = [{"type": "IfcProject", "long_name": "PROJET BEAUCOUP TROP LONG", "children": []}]
    findings = _project_findings(_snap(platform_name="X", tree=tree), _catalog())
    assert len(findings) == 1
    assert findings[0].error_type == ErrorType.NAMING_TOO_LONG
    assert findings[0].field_path == "IfcProject.LongName"


def test_platform_name_is_not_audited():
    # Nom plateforme TRÈS long, mais IfcProject IFC court → aucun finding.
    tree = [{"type": "IfcProject", "long_name": "1802L", "children": []}]
    snap = _snap(platform_name="UN NOM DE PROJET PLATEFORME EXTRÊMEMENT LONG", tree=tree)
    assert _project_findings(snap, _catalog()) == []


def test_no_structure_tree_means_no_audit():
    # Fichier de structure non généré → pas d'IfcProject → pas d'audit (pas de
    # repli sur le nom plateforme).
    snap = _snap(platform_name="NOM PLATEFORME BEAUCOUP TROP LONG", tree=[])
    assert _project_findings(snap, _catalog()) == []


def test_falls_back_to_name_when_no_long_name():
    tree = [{"type": "IfcProject", "name": "NOM TROP LONG AUSSI", "children": []}]
    findings = _project_findings(_snap(platform_name="X", tree=tree), _catalog())
    assert len(findings) == 1
