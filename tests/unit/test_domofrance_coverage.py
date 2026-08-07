"""Couverture Domofrance — la double porte, éprouvée sans fichier client.

Le point du lot est qu'un contrôle n'est déclaré évaluable qu'après **deux**
conditions : une règle du registre le revendique, ET le champ visé est
effectivement renseigné dans le document de preuves fourni. Ces tests portent
d'abord sur la seconde — c'est elle qui distingue Domo-2 d'un classeur de
mots-clés, et c'est elle qu'une régression ferait sauter en silence.

Tout tourne en CI : les ``EvidenceFacts`` sont construits à la main, aucun
document ``spatial_evidence/v1`` réel n'est requis. C'est également le mode où
la validation est **dégradée**, ``bim-core<0.4`` ne portant pas encore le
contrat — la dégradation est donc éprouvée dans les conditions où elle sert.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import coverage_domofrance_controls as cov  # noqa: E402
from inventory_domofrance_controls import (  # noqa: E402
    NUMERIC_THRESHOLD,
    Control,
    SurfaceTable,
    _detect_signals,
    _normalize,
)


def _control(text: str, row: int = 10) -> Control:
    """Un contrôle réel : signaux et seuil dérivés du texte, comme en Domo-0."""
    normalized = _normalize(text)
    return Control(
        row=row,
        type_logement="LOGEMENT COLLECTIF",
        zone="ZONE",
        element="ELEMENT",
        verification=text,
        description="",
        signals=_detect_signals(normalized),
        has_numeric_threshold=bool(NUMERIC_THRESHOLD.search(normalized)),
    )


def _facts(
    *,
    classes=("IfcDoor", "IfcSpace"),
    filled=None,
    counted=None,
    convex=3,
    with_width=3,
) -> cov.EvidenceFacts:
    # `filled or {...}` serait un piège : un dict vide est falsy, donc
    # `filled={}` — le cas « champ prévu mais jamais renseigné », qui est
    # justement le sujet du lot — retomberait sur le défaut et le test
    # passerait sans rien éprouver.
    return cov.EvidenceFacts(
        schema=cov.SCHEMA_SPATIAL_EVIDENCE,
        classes_present=frozenset(classes),
        filled=dict(filled if filled is not None else {("IfcDoor", "opening_width_m"): 12}),
        counted=dict(counted if counted is not None else {"IfcDoor": 12, "IfcSpace": 8}),
        n_spaces_convex=convex,
        n_spaces_with_width=with_width,
    )


PORTE = "La porte extérieure a une largeur de passage libre de 0,90 m minimum"
MARCHE = "Les emmarchements respecteront un giron supérieur ou égal à 28 cm"


# --------------------------------------------------------------------------
# La double porte : règle revendiquée ET champ réellement renseigné
# --------------------------------------------------------------------------


def test_champ_renseigne_donne_l_evaluabilite():
    a = cov.assess(_control(PORTE), _facts())
    assert a.status == "evaluable_by_spatial_evidence"
    assert a.rule == "porte_largeur_passage"


def test_champ_prevu_mais_vide_bloque_l_evaluabilite():
    """Une règle qui revendique ne suffit pas — c'est tout le lot."""
    a = cov.assess(_control(PORTE), _facts(filled={}))
    assert a.status == "non_evaluable_geometry_missing"
    assert a.rule == "porte_largeur_passage"
    assert "0 objet" in a.reason


def test_classe_absente_du_document_est_distinguee_du_champ_vide():
    """« Pas d'escalier dans la maquette » ≠ « escaliers sans géométrie »."""
    a = cov.assess(_control(MARCHE), _facts())
    assert a.status == "non_evaluable_not_modeled"
    assert a.rule == "emmarchement"
    assert "IfcStair" in a.reason

    b = cov.assess(
        _control(MARCHE),
        _facts(classes=("IfcStair",), filled={}, counted={"IfcStair": 24}),
    )
    assert b.status == "non_evaluable_geometry_missing"


def test_le_document_ne_decide_jamais_de_la_conformite():
    """Aucun statut ne peut porter un verdict — garde-fou contre la dérive."""
    for status in cov.STATUSES:
        assert "conforme" not in status
        assert "compliant" not in status


# --------------------------------------------------------------------------
# L'appréciation prime sur la géométrie
# --------------------------------------------------------------------------


def test_vocabulaire_d_appreciation_prime_sur_une_geometrie_mesurable():
    texte = "Il est recommandé que la porte ait une largeur de passage de 0,90 m"
    a = cov.assess(_control(texte), _facts())
    assert a.status == "advisory_only"
    assert a.rule is None


def test_le_vocabulaire_consultatif_est_celui_de_domo0():
    """Deux listes divergeraient sans que rien ne le signale."""
    from inventory_domofrance_controls import SIGNALS

    for motif in SIGNALS["manual_only"]:
        assert cov._ADVISORY.search(f" {motif} ")


# --------------------------------------------------------------------------
# Ce que la géométrie ne tranche pas
# --------------------------------------------------------------------------


def test_largeur_d_espace_demande_un_axe_median():
    """Le cercle inscrit ne vaut la largeur que sur un espace convexe."""
    texte = "La largeur de la circulation ne sera pas inférieure à 1,40 m"
    facts = _facts(
        filled={("IfcSpace", "inscribed_diameter_m"): 8},
        convex=2,
        with_width=8,
    )
    a = cov.assess(_control(texte), facts)
    assert a.status == "non_evaluable_axis_required"
    assert "axe médian" in a.reason


def test_mobilier_absent_de_la_maquette_est_non_modelise():
    texte = "Un miroir sera positionné au-dessus du lavabo"
    a = cov.assess(_control(texte), _facts())
    assert a.status == "non_evaluable_not_modeled"
    assert a.rule is None


def test_placard_n_est_pas_traite_comme_du_mobilier():
    """Un placard se modélise ; un miroir non. Les confondre perdrait un
    contrôle réellement outillable."""
    assert cov._UNMODELLED.search(_normalize("miroir")) is not None
    assert cov._UNMODELLED.search(_normalize("placard")) is None


def test_rampe_d_acces_est_vue_malgre_l_apostrophe():
    """La normalisation Domo-0 transforme « rampes d'accès » en « rampes d
    acces » — le motif doit tolérer le séparateur."""
    assert cov._UNMODELLED.search(_normalize("rampes d’accès")) is not None


def test_sans_regle_applicable_le_defaut_est_la_relecture():
    """Le défaut est humain, jamais « évaluable »."""
    a = cov.assess(_control("Le lot est attribué au titulaire du marché"), _facts())
    assert a.status == "manual_review_required"
    assert a.rule is None


# --------------------------------------------------------------------------
# Seuils indicatifs vs opposables
# --------------------------------------------------------------------------


def _table(label: str, caption: str, *, width: bool = True) -> SurfaceTable:
    return SurfaceTable(
        label=label,
        caption=caption,
        typologies=("T3", "T4"),
        room_types=("piece-000", "piece-001"),
        has_width_column=width,
        numeric_cells=4,
        non_numeric_cells=0,
        total_row=19,
    )


def test_surfaces_souhaitables_ne_sont_jamais_opposables():
    natures = cov.surface_natures(
        [_table("LOGEMENT COLLECTIF", "Répartition souhaitable … (à titre indicatif)")]
    )
    surface = [n for n in natures if n["nature"].startswith("surface_target")]
    assert surface[0]["nature"] == "surface_target_advisory"


def test_les_deux_natures_ne_sont_jamais_fondues():
    """Les surfaces sont indicatives, les LARGEUR MINI sont annoncées minimales
    dans la même légende. Une seule nature produirait de faux « non conforme »."""
    natures = cov.surface_natures(
        [_table("LOGEMENT COLLECTIF", "Répartition souhaitable des surfaces")]
    )
    assert {n["nature"] for n in natures} == {
        "surface_target_advisory",
        "width_min_mandatory",
    }


def test_table_sans_colonne_largeur_ne_fabrique_pas_de_seuil_opposable():
    natures = cov.surface_natures(
        [_table("LOGEMENT INDIVIDUEL", "Répartition souhaitable", width=False)]
    )
    assert "width_min_mandatory" not in {n["nature"] for n in natures}


# --------------------------------------------------------------------------
# Validation dégradée — le mode réel de ce dépôt (bim-core<0.4)
# --------------------------------------------------------------------------


def test_document_d_un_autre_schema_est_refuse(tmp_path):
    doc = tmp_path / "autre.json"
    doc.write_text('{"schema": "envelope_quantities/v1"}', encoding="utf-8")
    with pytest.raises(ValueError, match="ne déclare pas"):
        cov.read_evidence(str(doc))


def test_document_absurde_est_refuse_proprement(tmp_path):
    """Sans ce repli, un `objects: 42` plantait sur un AttributeError illisible."""
    doc = tmp_path / "absurde.json"
    doc.write_text('{"schema": "spatial_evidence/v1", "objects": 42}', encoding="utf-8")
    with pytest.raises(ValueError, match="doit être une liste"):
        cov.read_evidence(str(doc))


def test_convexite_est_lue_comme_un_rapport_entre_les_deux_largeurs(tmp_path):
    """Sur un L, cercle 2,338 / rectangle 6,0 ≈ 0,39 : non convexe."""
    doc = tmp_path / "preuves.json"
    doc.write_text(
        '{"schema": "spatial_evidence/v1", "objects": [], "spaces": ['
        '{"global_id": "A", "ifc_class": "IfcSpace",'
        ' "min_rect_width_m": 5.0, "inscribed_diameter_m": 4.99},'
        '{"global_id": "B", "ifc_class": "IfcSpace",'
        ' "min_rect_width_m": 6.0, "inscribed_diameter_m": 2.338}]}',
        encoding="utf-8",
    )
    facts = cov.read_evidence(str(doc))
    assert facts.n_spaces_with_width == 2
    assert facts.n_spaces_convex == 1
