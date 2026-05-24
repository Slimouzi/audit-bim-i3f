"""Fixtures partagées par tous les tests.

Évite la dépendance réseau (BIMData API, IAM Keycloak) : tout est mocké
ou construit à partir de structures Python pures.
"""
from __future__ import annotations

import pytest

from audit_bim.audit.findings import ErrorType, Finding, Severity, Theme
from audit_bim.extraction.model_data import ModelSnapshot
from audit_bim.requirements.models import (
    BIMPhase,
    NamingRule,
    PropertySpec,
    RequirementsCatalog,
    RoomSpec,
    StoreyName,
    ZoneSpec,
)


@pytest.fixture
def storey_names() -> list[StoreyName]:
    """Liste fermée I3F des noms d'étages admis (échantillon minimal)."""
    return [
        StoreyName(name="REZ-DE-CHAUSSEE"),
        StoreyName(name="1ER ETAGE"),
        StoreyName(name="2EME ETAGE"),
        StoreyName(name="COMBLES"),
        StoreyName(name="TOITURE"),
    ]


@pytest.fixture
def zone_specs() -> list[ZoneSpec]:
    """Liste fermée I3F des types de zones (PP + PC)."""
    return [
        ZoneSpec(type_label="Zone Logement T1", localisation="PP"),
        ZoneSpec(type_label="Zone Logement T2", localisation="PP"),
        ZoneSpec(type_label="Zone Logement T3", localisation="PP"),
        ZoneSpec(type_label="Zone Bureaux", localisation="PP"),
        ZoneSpec(type_label="Zone Part. Communes", localisation="PC"),
        ZoneSpec(type_label="Zone Parkings", localisation="PC"),
    ]


@pytest.fixture
def room_specs() -> list[RoomSpec]:
    """Liste fermée I3F des noms de pièces."""
    return [
        RoomSpec(name="CHAMBRE", type_label="Chambre", localisation="PP", surface_type="SHAB"),
        RoomSpec(name="CUISINE", type_label="Cuisine", localisation="PP", surface_type="SHAB"),
        RoomSpec(name="SDB", type_label="Salle de bain", localisation="PP", surface_type="SHAB"),
        RoomSpec(name="BALCON", type_label="Balcon", localisation="PP", surface_type="SU"),
        RoomSpec(name="CAVE", type_label="Cave", localisation="PP", surface_type="SU"),
    ]


@pytest.fixture
def naming_rules(storey_names, zone_specs, room_specs) -> list[NamingRule]:
    """Règles de nommage CCH I3F minimales pour les tests."""
    return [
        NamingRule(
            objet="Site",
            ifc_class="IfcSite",
            ifc_attribute="Name",
            pattern=r"^\d{4}[LP]$",
            ref_cch="Chap 6.3.1",
        ),
        NamingRule(
            objet="Bâtiment",
            ifc_class="IfcBuilding",
            ifc_attribute="Name",
            pattern=r"^\d{4}[LP]-[A-Z]([0-9]+)?$",
            max_length=30,
            ref_cch="Chap 6.3.1",
        ),
        NamingRule(
            objet="Étage",
            ifc_class="IfcBuildingStorey",
            ifc_attribute="Name",
            allowed_values=[s.name for s in storey_names],
            ref_cch="Chap 6.3.1",
        ),
        NamingRule(
            objet="Zone (logement)",
            ifc_class="IfcZone",
            ifc_attribute="Name",
            pattern=r"^\d{4}[LP]-\d{3,4}$",
            ref_cch="Chap 6.3.2.1",
        ),
        NamingRule(
            objet="Zone — type",
            ifc_class="IfcZone",
            ifc_attribute="ObjectType",
            allowed_values=[z.type_label for z in zone_specs],
            ref_cch="Chap 6.3.2",
        ),
        NamingRule(
            objet="Pièce",
            ifc_class="IfcSpace",
            ifc_attribute="LongName",
            allowed_values=[r.name for r in room_specs],
            case_sensitive=True,
            ref_cch="Chap 6.3.2",
        ),
    ]


@pytest.fixture
def property_specs() -> list[PropertySpec]:
    """Échantillon d'exigences propriétés (phase AVP)."""
    return [
        PropertySpec(
            theme="Générale",
            objet="Site",
            ifc_class="IfcSite",
            property_name="Latitude",
            pset_or_attribute="Latitude",
            required_phases=[BIMPhase.AVP, BIMPhase.PRO, BIMPhase.DCE],
            ref_cch="Chap 6.2",
        ),
        PropertySpec(
            theme="Générale",
            objet="Bâtiment",
            ifc_class="IfcBuilding",
            property_name="Adresse du bâtiment",
            pset_or_attribute="IfcBuildingAddress/AddressLines",
            required_phases=[BIMPhase.AVP, BIMPhase.PRO],
            ref_cch="Chap 6.2",
        ),
        PropertySpec(
            theme="Architecture",
            objet="Mur",
            ifc_class="IfcWall",
            property_name="Surface",
            pset_or_attribute="BaseQuantities/NetSideArea",
            required_phases=[BIMPhase.AVP, BIMPhase.PRO, BIMPhase.DCE],
            ref_cch="Chap 6.2",
        ),
        PropertySpec(
            theme="Architecture",
            objet="Mur",
            ifc_class="IfcWall",
            property_name="Est Extérieur",
            pset_or_attribute="Pset_WallCommon/IsExternal",
            required_phases=[BIMPhase.AVP, BIMPhase.PRO],
            comment="Champs : V / F",
            ref_cch="Chap 6.2",
        ),
    ]


@pytest.fixture
def catalog(storey_names, zone_specs, room_specs, naming_rules, property_specs) -> RequirementsCatalog:
    """Catalogue d'exigences complet (sources fictives)."""
    return RequirementsCatalog(
        cch_version="3.6",
        cch_source_pdf="test://cch.pdf",
        data_spec_source="test://data.xlsx",
        naming_spec_source="test://naming.xlsx",
        properties=property_specs,
        naming_rules=naming_rules,
        storey_names=storey_names,
        zone_specs=zone_specs,
        room_specs=room_specs,
    )


@pytest.fixture
def snapshot_minimal() -> ModelSnapshot:
    """Snapshot synthétique d'un mini-modèle conforme."""
    snap = ModelSnapshot(
        project={"name": "1802L Programme Test"},
        model={"name": "TEST.ifc"},
        sites=[{"uuid": "S1", "name": "1802L", "type": "IfcSite"}],
        buildings=[{"uuid": "B1", "name": "1802L-A", "type": "IfcBuilding"}],
        storeys=[
            {"uuid": "F1", "name": "REZ-DE-CHAUSSEE", "type": "IfcBuildingStorey"},
            {"uuid": "F2", "name": "1ER ETAGE", "type": "IfcBuildingStorey"},
        ],
        spaces=[
            {"uuid": "SP1", "longname": "CHAMBRE 01", "type": "IfcSpace"},
            {"uuid": "SP2", "longname": "CUISINE", "type": "IfcSpace"},
        ],
        zones=[
            {
                "uuid": "Z1",
                "name": "1802L-1101",
                "object_type": "Zone Logement T2",
                "type": "IfcZone",
            }
        ],
        elements=[],
    )
    return snap.index()


@pytest.fixture
def snapshot_with_walls() -> ModelSnapshot:
    """Snapshot avec quelques murs (pour tester règle properties / classifications)."""
    snap = ModelSnapshot(
        project={"name": "Test"},
        model={"name": "TEST.ifc"},
        sites=[{"uuid": "S1", "name": "1802L", "type": "IfcSite"}],
        buildings=[{"uuid": "B1", "name": "1802L-A", "type": "IfcBuilding"}],
        storeys=[{"uuid": "F1", "name": "REZ-DE-CHAUSSEE", "type": "IfcBuildingStorey"}],
        spaces=[],
        zones=[],
        elements=[
            {
                "uuid": "W1",
                "type": "IfcWallStandardCase",
                "name": "Mur extérieur 01",
                "classifications": [],
                "property_sets": [
                    {
                        "name": "Pset_WallCommon",
                        "properties": [
                            {
                                "definition": {"name": "IsExternal", "value_type": "boolean"},
                                "value": True,
                            }
                        ],
                    }
                ],
            },
            {
                "uuid": "W2",
                "type": "IfcWallStandardCase",
                "name": "Cloison interne",
                "classifications": [
                    {"notation": "C1010", "source": "UniFormat"}
                ],
                "property_sets": [],
            },
        ],
    )
    return snap.index()


@pytest.fixture
def sample_finding() -> Finding:
    """Un Finding type pour les tests de reporting / sérialisation."""
    return Finding(
        theme=Theme.NAMING_SPACE,
        severity=Severity.MEDIUM,
        error_type=ErrorType.NAMING_NOT_IN_LIST,
        element_uuid="SP1",
        ifc_type="IfcSpace",
        name="salle de bain",
        expected=["CHAMBRE", "CUISINE", "SDB"],
        actual="salle de bain",
        ref_cch="Chap 6.3.2",
        recommended_action="Aligner sur la liste fermée.",
    )
