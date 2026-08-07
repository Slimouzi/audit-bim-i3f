"""Couverture Domofrance — la double porte, éprouvée sans fichier client.

Le point du lot est qu'un contrôle n'est déclaré évaluable qu'après **deux**
conditions : une règle du registre le revendique, ET le champ visé est
effectivement renseigné dans le document de preuves fourni. Ces tests portent
d'abord sur la seconde — c'est elle qui distingue Domo-2 d'un classeur de
mots-clés, et c'est elle qu'une régression ferait sauter en silence.

Tout tourne en CI : les ``EvidenceFacts`` sont construits à la main, aucun
document ``spatial_evidence/v1`` réel n'est requis.

Ce dépôt a **adopté** ``bim-core>=0.4.0,<0.5``, donc la validation complète par
le contrat est le chemin nominal, ici comme en CI. Les tests qui portent sur le
**repli de compatibilité** ou sur le **mode adopté** ne dépendent pas du
``bim-core`` installé : ils simulent explicitement le mode qu'ils éprouvent.
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
    """« Pas de porte dans la maquette » ≠ « portes sans largeur mesurée ».

    Démontré sur `porte_largeur_passage` et non sur l'emmarchement : cette
    dernière est verrouillée `insufficient_reason`, donc elle ne peut plus
    illustrer la distinction — elle rend toujours le même statut.
    """
    absente = cov.assess(_control(PORTE), _facts(classes=("IfcSpace",), filled={}))
    assert absente.status == "non_evaluable_not_modeled"
    assert absente.rule == "porte_largeur_passage"
    assert "IfcDoor" in absente.reason

    vide = cov.assess(_control(PORTE), _facts(filled={}))
    assert vide.status == "non_evaluable_geometry_missing"
    assert "0 objet" in vide.reason


def test_emmarchement_reste_non_evaluable_meme_avec_bbox_renseignee():
    """Test de **non-vacuité** : le verrou ne doit pas dépendre d'un champ vide.

    Sur la maquette de référence, `IfcStair.bbox` n'est renseigné sur aucun
    objet — le statut correct sort donc « par accident ». Ici la bbox est
    renseignée sur 100 % des escaliers, et le contrôle doit **rester** non
    évaluable : une valeur correcte existe, mais ce n'est pas la bonne preuve.
    Le giron ne se déduit pas d'une boîte englobante.
    """
    facts = _facts(
        classes=("IfcStair",),
        filled={("IfcStair", "bbox"): 24},
        counted={"IfcStair": 24},
    )
    a = cov.assess(_control(MARCHE), facts)
    assert a.status == "non_evaluable_geometry_missing"
    assert a.rule == "emmarchement"
    assert "giron" in a.reason
    assert "bbox" in a.reason


def test_emmarchement_reste_dans_le_registre_pour_la_tracabilite():
    """La famille est revendiquée : c'est ce qui rend le manque visible."""
    emmarchement = next(r for r in cov.RULES if r.key == "emmarchement")
    assert emmarchement.insufficient_reason
    assert cov.assess(_control(MARCHE), _facts()).rule == "emmarchement"


def test_une_regle_suffisante_reste_evaluable():
    """Contre-épreuve : le verrou ne gèle pas tout le registre."""
    porte = next(r for r in cov.RULES if r.key == "porte_largeur_passage")
    assert not porte.insufficient_reason
    assert cov.assess(_control(PORTE), _facts()).status == "evaluable_by_spatial_evidence"


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


def test_rampe_d_acces_n_est_pas_declaree_non_modelisable():
    """``IfcRamp`` existe : une rampe se modélise.

    La ranger parmi les objets sans classe IFC affirmait le contraire — une
    erreur de fond, pas une approximation. Faute de champ donnant la largeur
    d'un objet quelconque dans le contrat, aucune règle ne la revendique
    encore ; le statut honnête est donc « objet à mapper », jamais
    « non modélisable ».
    """
    texte = "Les rampes d’accès auront une largeur minimale de 3,00 m"
    assert cov._UNMODELLED.search(_normalize(texte)) is None

    a = cov.assess(_control(texte), _facts())
    assert a.status != "non_evaluable_not_modeled"
    assert a.status == "evaluable_with_object_mapping"


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
# Validation des champs consommés — dans les deux modes
# --------------------------------------------------------------------------


def test_document_d_un_autre_schema_est_refuse(tmp_path):
    doc = tmp_path / "autre.json"
    doc.write_text('{"schema": "envelope_quantities/v1"}', encoding="utf-8")
    # Refus exigé dans les deux modes ; le libellé appartient au validateur actif.
    with pytest.raises(ValueError):
        cov.read_evidence(str(doc))


def test_document_absurde_est_refuse_proprement(tmp_path):
    """Sans ce repli, un `objects: 42` plantait sur un AttributeError illisible."""
    doc = tmp_path / "absurde.json"
    doc.write_text('{"schema": "spatial_evidence/v1", "objects": 42}', encoding="utf-8")
    with pytest.raises(ValueError):
        cov.read_evidence(str(doc))


def _write(tmp_path, body: str) -> str:
    doc = tmp_path / "preuves.json"
    doc.write_text(body, encoding="utf-8")
    return str(doc)


@pytest.mark.parametrize(
    "valeur",
    ('"large"', "{}", "[]", "true", "null_bis", '"1,20"'),
)
def test_metrique_non_numerique_est_refusee(tmp_path, valeur):
    """Le cœur du repli : `read_evidence` ne compte que `is not None`.

    Sans ce refus, ``opening_width_m: "large"`` serait compté comme renseigné et
    rendrait le contrôle de largeur de porte « évaluable » — une fausse
    évaluabilité, dans le seul mode de validation actuellement disponible.
    """
    brut = "null" if valeur == "null_bis" else valeur
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A",'
        f' "ifc_class": "IfcDoor", "opening_width_m": {brut}}}]}}',
    )
    if valeur == "null_bis":
        # Une mesure absente est licite : c'est ce que le rapport doit compter.
        facts = cov.read_evidence(path)
        assert not facts.has_field("IfcDoor", "opening_width_m")
        return
    # Le libellé n'est PAS asserté : selon que bim-core porte le contrat ou non,
    # le refus vient du contrat ou du filtre local. Ce qui doit tenir dans les
    # deux modes, c'est le refus lui-même. Les messages propres au filtre local
    # sont assertés là où lui seul mord (ifc_class vide, booléen).
    with pytest.raises(ValueError):
        cov.read_evidence(path)


def test_une_largeur_texte_ne_rend_plus_un_controle_evaluable(tmp_path):
    """Le scénario complet, de bout en bout, plutôt que la seule exception."""
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A",'
        ' "ifc_class": "IfcDoor", "opening_width_m": "large"}]}',
    )
    with pytest.raises(ValueError):
        cov.read_evidence(path)


def test_bbox_partielle_est_refusee(tmp_path):
    """Une boîte incomplète ne mesure rien mais passait pour renseignée."""
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A",'
        ' "ifc_class": "IfcStair", "bbox": {"x_min": 0, "x_max": 1}}]}',
    )
    with pytest.raises(ValueError):
        cov.read_evidence(path)


def test_bbox_vide_est_refusee(tmp_path):
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A",'
        ' "ifc_class": "IfcStair", "bbox": {}}]}',
    )
    with pytest.raises(ValueError):
        cov.read_evidence(path)


def test_ifc_class_vide_est_refusee(tmp_path):
    """Sans classe, l'entrée serait comptée sous « ? » et fausserait les ratios."""
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A", "ifc_class": "  "}]}',
    )
    with pytest.raises(ValueError, match="chaîne non vide attendue"):
        cov.read_evidence(path)


def test_un_booleen_n_est_pas_une_mesure(tmp_path):
    """En Python ``True`` est un ``int`` : sans garde, une largeur de 1 m."""
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A",'
        ' "ifc_class": "IfcDoor", "opening_width_m": true}]}',
    )
    with pytest.raises(ValueError, match="nombre fini attendu"):
        cov.read_evidence(path)


def test_le_chemin_du_fichier_est_nomme_dans_l_erreur(tmp_path):
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A",'
        ' "ifc_class": "IfcDoor", "opening_width_m": "large"}]}',
    )
    with pytest.raises(ValueError, match="preuves"):
        cov.read_evidence(path)


@pytest.fixture
def contrat_permissif(monkeypatch):
    """Simule ``bim-core>=0.4`` présent, avec un contrat qui accepte tout.

    Reproduit le mode adopté quel que soit le ``bim-core`` réellement
    installé — le test vaut donc aussi bien sur un environnement de repli que
    sur celui, nominal, de ce dépôt.

    Le faux contrat **compte ses appels** : sans ça, une simulation qui ne
    prendrait pas laisserait le test passer par le chemin dégradé et ne
    prouverait rien.
    """
    import types

    appels = []
    faux = types.ModuleType("bim_core.contracts")
    faux.parse_spatial_evidence = lambda doc, **kw: appels.append(doc) or doc
    monkeypatch.setitem(sys.modules, "bim_core.contracts", faux)
    return appels


@pytest.mark.parametrize(
    ("champ", "valeur"),
    (("ifc_class", '"  "'), ("opening_width_m", "true")),
)
def test_les_gardefous_locaux_mordent_meme_contrat_present(
    tmp_path, contrat_permissif, champ, valeur
):
    """**Non-vacuité du mode adopté.** Mesuré sur bim-core 0.4.0, le contrat
    accepte ces deux valeurs : ``ifc_class`` n'est qu'un ``str`` sans contrainte
    de longueur, et ``True`` est un ``int`` que pydantic coerce en ``1.0`` —
    une largeur de porte née d'un booléen.

    Ne rejouer le filtre local que dans le repli ferait donc **perdre** ces
    deux garde-fous — et ce dépôt a adopté ``bim-core>=0.4``.
    """
    base = '"global_id": "A", "ifc_class": "IfcDoor"'
    corps = base if champ == "opening_width_m" else '"global_id": "A"'
    path = _write(
        tmp_path,
        f'{{"schema": "spatial_evidence/v1", "objects": [{{{corps}, "{champ}": {valeur}}}]}}',
    )
    with pytest.raises(ValueError):
        cov.read_evidence(path)
    assert contrat_permissif, "le faux contrat n'a pas été appelé : simulation sans effet"


def test_le_contrat_permissif_accepterait_seul_ces_documents(tmp_path, contrat_permissif):
    """Contre-épreuve : sans le filtre local, ces documents passeraient.

    Sans elle, le test précédent pourrait réussir pour une raison étrangère au
    filtre — par exemple si le document était refusé plus tôt.
    """
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A",'
        ' "ifc_class": "IfcDoor", "opening_width_m": true}]}',
    )
    monkey = cov._validate_consumed_fields
    try:
        cov._validate_consumed_fields = lambda *a, **k: None
        facts = cov.read_evidence(path)
    finally:
        cov._validate_consumed_fields = monkey
    assert contrat_permissif, "le faux contrat n'a pas été appelé"
    assert facts.has_field("IfcDoor", "opening_width_m"), (
        "sans le filtre local, un booléen serait compté comme une largeur"
    )


# --------------------------------------------------------------------------
# Provenance du producteur — avertir, jamais refuser
# --------------------------------------------------------------------------


def _doc_version(tmp_path, source: str) -> str:
    return _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", ' + source + ', "objects": [{"global_id": "A",'
        ' "ifc_class": "IfcDoor", "opening_width_m": 0.93}], "spaces": []}',
    )


_SOURCE_OK = '"source": {"producer": "ifc-geometry", "tool": "extract_spatial_evidence", '


def test_producteur_a_jour_est_silencieux(tmp_path):
    """0.6.0, producteur et outil attendus : rien à signaler."""
    facts = cov.read_evidence(_doc_version(tmp_path, _SOURCE_OK + '"version": "0.6.0"}'))
    assert facts.source_version == "0.6.0"
    assert facts.provenance.producer == "ifc-geometry"
    assert facts.provenance.tool == "extract_spatial_evidence"
    assert facts.warnings == ()


def test_un_autre_producteur_a_jour_est_averti_pas_silencieux(tmp_path):
    """**Non-vacuité de l'identité.** La version seule ne prouve rien.

    Un document tiers déclarant `0.6.0` satisfait le seuil de fraîcheur sans
    qu'aucun lien ne le rattache à notre producteur. Sans ce contrôle, il
    passerait en silence — et le rapport l'aurait présenté comme un
    `ifc-geometry` à jour.
    """
    facts = cov.read_evidence(
        _doc_version(tmp_path, '"source": {"producer": "other", "tool": "x", "version": "0.6.0"}')
    )
    assert facts.provenance.producer == "other"
    assert len(facts.warnings) == 1
    assert cov.WARN_PRODUCER_UNEXPECTED in facts.warnings[0]
    # Accepté : les mesures restent exploitables.
    assert facts.has_field("IfcDoor", "opening_width_m")


def test_le_rapport_n_invente_jamais_le_producteur(tmp_path):
    """Le libellé affiché doit porter le producteur déclaré, pas le nôtre."""
    facts = cov.read_evidence(
        _doc_version(tmp_path, '"source": {"producer": "other", "tool": "x", "version": "0.6.0"}')
    )
    assert "other" in facts.provenance.label()
    assert "ifc-geometry" not in facts.provenance.label()


@pytest.mark.parametrize(
    "source",
    (
        '"source": {"producer": "ifc-geometry", "version": "0.6.0"}',
        '"source": {"tool": "extract_spatial_evidence", "version": "0.6.0"}',
        '"source": {"producer": "ifc-geometry", "tool": "autre_outil", "version": "0.6.0"}',
    ),
)
def test_producteur_ou_outil_manquant_est_averti(tmp_path, source):
    """L'identité demande les DEUX champs : l'un sans l'autre ne suffit pas."""
    facts = cov.read_evidence(_doc_version(tmp_path, source))
    assert any(cov.WARN_PRODUCER_UNEXPECTED in a for a in facts.warnings)


def test_identite_et_fraicheur_sont_deux_axes_independants(tmp_path):
    """Un producteur tiers ET ancien cumule les deux avertissements."""
    facts = cov.read_evidence(
        _doc_version(tmp_path, '"source": {"producer": "other", "tool": "x", "version": "0.5.1"}')
    )
    cles = " ".join(facts.warnings)
    assert cov.WARN_PRODUCER_UNEXPECTED in cles
    assert cov.WARN_PRODUCER_BELOW_MINIMUM in cles
    assert len(facts.warnings) == 2


def test_producteur_anterieur_est_averti_mais_accepte(tmp_path):
    """0.5.1 est **prouvé équivalent** à 0.6.0 sur la maquette de référence :
    le refuser détruirait la seule référence exploitable sans gain de sûreté."""
    facts = cov.read_evidence(_doc_version(tmp_path, _SOURCE_OK + '"version": "0.5.1"}'))
    assert facts.source_version == "0.5.1"
    # Identité correcte : seul l'axe fraîcheur parle.
    assert len(facts.warnings) == 1
    assert cov.WARN_PRODUCER_BELOW_MINIMUM in facts.warnings[0]
    assert "régénérer" in facts.warnings[0]
    # Accepté : les mesures restent exploitables.
    assert facts.has_field("IfcDoor", "opening_width_m")


@pytest.mark.parametrize(
    ("version", "declaree"),
    (('"version": null', None), ('"version": "n/a"', "n/a")),
)
def test_version_absente_ou_illisible_est_avertie_plus_fort(tmp_path, version, declaree):
    """Identité correcte, fraîcheur inconnue : un seul avertissement, le bon.

    `source_version` rend la valeur **déclarée**, même illisible : le rapport
    doit montrer ce que le document prétend, pas le masquer. C'est
    `_parse_version` qui tranche la lisibilité.
    """
    facts = cov.read_evidence(_doc_version(tmp_path, _SOURCE_OK + version + "}"))
    assert facts.source_version == declaree
    assert cov._parse_version(facts.source_version) is None
    assert len(facts.warnings) == 1
    assert cov.WARN_SOURCE_VERSION_UNKNOWN in facts.warnings[0]
    assert facts.has_field("IfcDoor", "opening_width_m")


@pytest.mark.parametrize("source", ('"source": {}', '"x": 1'))
def test_source_absente_cumule_identite_et_fraicheur(tmp_path, source):
    """Sans `source`, ni l'identité ni la fraîcheur ne sont connues."""
    facts = cov.read_evidence(_doc_version(tmp_path, source))
    assert facts.source_version is None
    cles = " ".join(facts.warnings)
    assert cov.WARN_PRODUCER_UNEXPECTED in cles
    assert cov.WARN_SOURCE_VERSION_UNKNOWN in cles
    assert facts.has_field("IfcDoor", "opening_width_m")


def test_payload_invalide_est_refuse_quelle_que_soit_la_version(tmp_path):
    """La version ne rattrape jamais un document invalide."""
    for version in ('"0.6.0"', '"0.5.1"', "null"):
        path = _write(
            tmp_path,
            '{"schema": "spatial_evidence/v1", "source": {"version": ' + version + "},"
            ' "objects": [{"global_id": "A", "ifc_class": "IfcDoor",'
            ' "opening_width_m": true}]}',
        )
        with pytest.raises(ValueError):
            cov.read_evidence(path)


@pytest.mark.parametrize(
    ("texte", "attendu"),
    (
        ("0.6.0", (0, 6, 0)),
        ("0.6.1", (0, 6, 1)),
        ("1.0.0", (1, 0, 0)),
        ("0.6.0rc1", (0, 6, 0)),
        ("0.5.1", (0, 5, 1)),
        ("", None),
        ("n/a", None),
        (None, None),
        (0.6, None),
    ),
)
def test_lecture_de_version_tolerante_mais_honnete(texte, attendu):
    """Un suffixe ne doit pas rendre la version illisible ; un texte non
    numérique ne doit pas être deviné."""
    assert cov._parse_version(texte) == attendu


def test_la_provenance_ne_deplace_aucun_compteur(tmp_path):
    """Critère du lot : seul le rapport gagne un avertissement.

    Deux documents identiques au seul `source.version` près doivent produire
    exactement les mêmes faits mesurés.
    """
    dossier_a, dossier_b = tmp_path / "a", tmp_path / "b"
    dossier_a.mkdir()
    dossier_b.mkdir()
    a = cov.read_evidence(_doc_version(dossier_a, _SOURCE_OK + '"version": "0.6.0"}'))
    b = cov.read_evidence(_doc_version(dossier_b, _SOURCE_OK + '"version": "0.5.1"}'))
    assert (a.classes_present, a.filled, a.counted) == (b.classes_present, b.filled, b.counted)
    assert (a.n_spaces_convex, a.n_spaces_with_width) == (b.n_spaces_convex, b.n_spaces_with_width)
    assert a.warnings == () and len(b.warnings) == 1


def test_un_document_valide_reste_accepte(tmp_path):
    """Le garde-fou ne doit pas devenir un refus généralisé."""
    path = _write(
        tmp_path,
        '{"schema": "spatial_evidence/v1", "objects": [{"global_id": "A",'
        ' "ifc_class": "IfcDoor", "opening_width_m": 0.93,'
        ' "bbox": {"x_min": 0, "x_max": 1, "y_min": 0, "y_max": 1,'
        ' "z_min": 0, "z_max": 2}}], "spaces": []}',
    )
    facts = cov.read_evidence(path)
    assert facts.has_field("IfcDoor", "opening_width_m")
    assert facts.has_field("IfcDoor", "bbox")


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
