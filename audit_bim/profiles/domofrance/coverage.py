"""Couverture Domofrance × spatial_evidence/v1 — évaluabilité, pas conformité.

Croise la liste de contrôle du maître d'ouvrage (Domo-0) avec un document de
preuves géométriques réellement produit, et dit pour chaque contrôle **s'il
pourra être tranché**, jamais s'il est conforme. Aucun statut de conformité
n'est calculé, aucune maquette n'est jugée.

La différence avec un classement par mots-clés est le point de ce lot : un
contrôle n'est déclaré évaluable que si

1. une **règle explicite du registre** le revendique — chaque règle nomme le
   champ du contrat qu'elle lirait, et les lignes qu'elle revendique sont
   listées dans le rapport, donc auditables ;
2. ce champ est **effectivement renseigné** dans le document de preuves fourni,
   pour la classe visée.

Le point 2 est ce qui empêche de retomber dans Domo-0 : l'évaluabilité dépend du
document mesuré, pas du vocabulaire du contrôle. C'est lui qui range les
contrôles d'emmarchement en « géométrie manquante » quand les ``IfcStair`` d'une
maquette n'ont aucune boîte englobante — au lieu de les annoncer évaluables
parce que la phrase contient « giron ≥ 28 cm ».

**Contrat publié et adopté par ce dépôt.** ``spatial_evidence/v1`` vit dans
``bim-core-v0.4.0`` et son producteur dans ``ifc-geometry-mcp-v0.6.0`` ;
``audit-bim-mcp`` épingle désormais ``bim-core>=0.4.0,<0.5``. La validation
complète du document par le contrat est donc le **chemin nominal**.

Le filtre local sur les champs consommés reste appliqué **après** le contrat :
celui-ci ne tranche ni un ``ifc_class`` vide ni un booléen coercé en nombre.
Cf. :func:`read_evidence`.

Le rendu texte vit ici avec la mesure : c'est le même vocabulaire, et les
séparer ferait diverger un compteur de la phrase qui l'explique. Seule
l'analyse d'``argv`` reste au script CLI.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .controls import (
    SIGNALS,
    Control,
    _normalize,
)

SCHEMA_SPATIAL_EVIDENCE = "spatial_evidence/v1"

#: Les sept issues possibles. Aucune ne dit « conforme » ou « non conforme » :
#: ce document mesure ce qu'on pourra trancher, pas ce qui l'est.
STATUSES = (
    "evaluable_by_spatial_evidence",
    "evaluable_with_object_mapping",
    "non_evaluable_axis_required",
    "non_evaluable_geometry_missing",
    "non_evaluable_not_modeled",
    "manual_review_required",
    "advisory_only",
)

#: Un espace est tenu pour convexe quand ses deux mesures de largeur coïncident.
#: Sur un L à branches de 2,00 m le rapport tombe à 2,338 / 6,0 ≈ 0,39.
CONVEXITY_RATIO_MIN = 0.95

#: Le vocabulaire d'appréciation est **celui de Domo-0**, pas une seconde liste.
#: En maintenir deux les ferait diverger sans que rien ne le signale.
_ADVISORY = re.compile("|".join(SIGNALS["manual_only"]))

#: Objets que les maquettes de logement ne portent pas : aucune classe IFC ne
#: leur correspond, donc aucune preuve géométrique ne les décrira jamais.
#:
#: **« Rampe d'accès » n'est PAS dans cette liste**, bien qu'elle y ait figuré :
#: ``IfcRamp`` existe, et une rampe se modélise. La ranger ici affirmait qu'aucune
#: classe ne peut la porter — une erreur de fond, pas une approximation. Faute de
#: champ donnant la largeur d'un objet quelconque dans ``spatial_evidence/v1``
#: (``opening_width_m`` ne vaut que pour les menuiseries), aucune règle ne la
#: revendique aujourd'hui : elle retombe donc sur le défaut, qui dit qu'il reste
#: un objet à mapper. Voir ``docs/scope-domofrance-coverage.md``.
_UNMODELLED = re.compile(
    "miroir|tableau d.affichage|corbeille|essuie.pieds|paillasson|boites? aux lettres|"
    "extincteur|jardiniere|luminaire|interphone|visiophone|thermostat|radiateur|"
    "emetteur|robinet|lave.linge|seche.linge|hotte|plan de travail|evier|cuvette|"
    "lavabo"
)


@dataclass(frozen=True)
class Rule:
    """Une famille de contrôles revendiquée, et le champ qu'elle lirait.

    ``field`` et ``ifc_class`` ne sont pas décoratifs : le rapport vérifie que ce
    champ est renseigné dans le document de preuves fourni avant d'accorder
    l'évaluabilité.
    """

    key: str
    pattern: str
    field: str
    ifc_class: str
    needs_convexity: bool = False
    note: str = ""
    #: Non vide ⇒ la famille est revendiquée **pour la traçabilité seulement** :
    #: aucun champ du contrat ne la mesure, et ``field`` n'en est qu'une
    #: approximation insuffisante. Le contrôle est alors non évaluable quoi que
    #: porte la maquette. Sans ce verrou, une valeur *correcte* mais qui n'est
    #: pas la *bonne preuve* rendrait le contrôle évaluable — la même fausse
    #: évaluabilité que sur une valeur absurde, mais sur l'axe sémantique.
    insufficient_reason: str = ""

    def matches(self, text: str) -> bool:
        return bool(re.search(self.pattern, text))


RULES: tuple[Rule, ...] = (
    Rule(
        key="porte_largeur_passage",
        pattern=(
            "(porte|portillon|vantail)[^.]{0,80}(largeur|passage)"
            "|(largeur|passage)[^.]{0,80}(porte|portillon)"
        ),
        field="opening_width_m",
        ifc_class="IfcDoor",
        note="Largeur de menuiserie : diagonale horizontale de l'emprise.",
    ),
    Rule(
        key="hauteur_sous_plafond",
        pattern="hauteur sous.?plafond|hauteur libre|sous.?plafond",
        field="clear_height_m",
        ifc_class="IfcSpace",
        note="Extension verticale de l'espace.",
    ),
    Rule(
        key="surface_local",
        pattern=(
            r"(superficie|surface)[^.]{0,60}\d"
            r"|\d[^.]{0,20}m2[^.]{0,40}(local|piece|espace|logement)"
        ),
        field="area_declared_m2",
        ifc_class="IfcSpace",
        note="Surface déclarée de la pièce (BaseQuantities).",
    ),
    Rule(
        key="largeur_espace",
        pattern=(
            "(largeur|large de)[^.]{0,60}"
            "(circulation|cheminement|couloir|degagement|balcon|loggia|terrasse|"
            "local|piece|espace|rampe)"
            "|(circulation|cheminement|couloir|balcon|loggia)[^.]{0,60}largeur"
        ),
        field="inscribed_diameter_m",
        ifc_class="IfcSpace",
        needs_convexity=True,
        note="Cercle inscrit — ne vaut la largeur que sur un espace convexe.",
    ),
    Rule(
        key="emmarchement",
        pattern="emmarchement|giron|hauteur de marche|nez de marche|marches",
        field="bbox",
        ifc_class="IfcStair",
        insufficient_reason=(
            "giron et hauteur de marche absents de spatial_evidence/v1 ; "
            "la bbox de l'escalier ne les mesure pas"
        ),
        note="Demanderait la géométrie des marches, pas la boîte de l'escalier.",
    ),
    Rule(
        key="encombrement_local",
        pattern="obstacle|encombre|libre de tout|degagement libre",
        field="occupancy_area_m2",
        ifc_class="IfcSpace",
        note="Union des empreintes des objets rattachés à l'espace.",
    ),
)


@dataclass(frozen=True)
class EvidenceFacts:
    """Disponibilité mesurée, jamais supposée, dans un document de preuves."""

    schema: str
    classes_present: frozenset[str]
    filled: dict[tuple[str, str], int]
    counted: dict[str, int]
    n_spaces_convex: int
    n_spaces_with_width: int
    #: Origine déclarée du document — producteur, outil, version, bruts.
    #: Purement informatif : aucun compteur n'en dépend.
    provenance: Provenance | None = None
    #: Avertissements de provenance, jamais des refus. Cf. :func:`producer_warnings`.
    warnings: tuple[str, ...] = ()

    @property
    def source_version(self) -> str | None:
        """Raccourci de lecture ; l'identité vit dans :attr:`provenance`."""
        return self.provenance.version if self.provenance else None

    def has_field(self, ifc_class: str, field: str) -> bool:
        return self.filled.get((ifc_class, field), 0) > 0

    def fill_ratio(self, ifc_class: str, field: str) -> float:
        total = self.counted.get(ifc_class, 0)
        if not total:
            return 0.0
        return self.filled.get((ifc_class, field), 0) / total


#: Champs **consommés** par le registre de règles, plus ``min_rect_width_m`` qui
#: sert au calcul de convexité. Ce sont exactement ceux dont une valeur absurde
#: produirait une fausse évaluabilité.
_NUMERIC_FIELDS = (
    "opening_width_m",
    "clear_height_m",
    "area_declared_m2",
    "inscribed_diameter_m",
    "occupancy_area_m2",
    "min_rect_width_m",
)

_BBOX_KEYS = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")

#: Version de producteur à partir de laquelle un document ne porte aucun
#: avertissement. C'est la première version publiée sous le tag
#: ``ifc-geometry-mcp-v0.6.0``, celle qui accompagne ``spatial_evidence/v1``.
MIN_PRODUCER_VERSION = (0, 6, 0)

#: Producteur et outil attendus. La version seule ne prouve pas l'identité :
#: un document tiers déclarant ``version: "0.6.0"`` passerait pour un
#: ``ifc-geometry`` à jour alors que rien ne le rattache à ce producteur.
EXPECTED_PRODUCER = "ifc-geometry"
EXPECTED_TOOL = "extract_spatial_evidence"

#: Clés d'avertissement — **jamais** des motifs de refus.
WARN_PRODUCER_BELOW_MINIMUM = "producer_version_below_minimum"
WARN_SOURCE_VERSION_UNKNOWN = "source_version_unknown"
WARN_PRODUCER_UNEXPECTED = "producer_unexpected"


def _parse_version(text: object) -> tuple[int, ...] | None:
    """``"0.6.0"`` → ``(0, 6, 0)``. ``None`` si ce n'est pas lisible.

    Tolérant sur les suffixes (``0.6.0rc1``) : seuls les segments purement
    numériques de tête sont retenus. Une version illisible n'est pas une erreur,
    c'est une provenance inconnue — et elle s'annonce comme telle.
    """
    if not isinstance(text, str):
        return None
    segments: list[int] = []
    for part in text.strip().split("."):
        chiffres = ""
        for c in part:
            if not c.isdigit():
                break
            chiffres += c
        if not chiffres:
            break
        segments.append(int(chiffres))
    return tuple(segments) or None


@dataclass(frozen=True)
class Provenance:
    """Ce que le document déclare de son origine, tel quel.

    Les trois champs sont rendus **bruts** : le rapport doit afficher le
    producteur réel, jamais un nom supposé. Écrire ``ifc-geometry`` en dur ferait
    présenter un document tiers comme s'il venait de notre producteur.
    """

    producer: str | None
    tool: str | None
    version: str | None

    def label(self) -> str:
        """Libellé d'affichage, sans jamais inventer de producteur."""
        return f"{self.producer or '(producteur inconnu)'} {self.version or '(version inconnue)'}"


def producer_warnings(document: dict) -> tuple[Provenance, tuple[str, ...]]:
    """Provenance du document, et avertissements éventuels.

    **N'émet jamais de refus.** Un payload invalide est rejeté par la validation
    du contrat, indépendamment de sa provenance ; ici on ne fait que qualifier
    l'origine d'un document déjà tenu pour valide.

    Deux axes indépendants, parce que **la version seule ne prouve pas
    l'identité** : un document tiers déclarant ``version: "0.6.0"`` satisferait
    le seuil sans qu'aucun lien ne le rattache à ``ifc-geometry``.

    - *identité* : ``producer`` et ``tool`` doivent être ceux attendus ;
    - *fraîcheur* : ``version`` doit atteindre :data:`MIN_PRODUCER_VERSION`.

    Le choix d'avertir plutôt que de refuser est mesuré, pas prudent : le
    document de référence produit par ``0.5.1`` a été comparé à celui de
    ``0.6.0`` sur la même maquette, et les deux payloads sont **identiques** hors
    ``created_at`` et ``source.version``. Refuser un document dont on a la preuve
    qu'il est équivalent coûterait la seule référence exploitable sans rien
    gagner en sûreté.
    """
    source = document.get("source") or {}

    def texte(cle: str) -> str | None:
        """Champ de provenance, ``None`` si absent ou non textuel."""
        valeur = source.get(cle) if isinstance(source, dict) else None
        return valeur if isinstance(valeur, str) else None

    provenance = Provenance(
        producer=texte("producer"), tool=texte("tool"), version=texte("version")
    )
    avertissements: list[str] = []

    # Identité — indépendante de la version.
    if provenance.producer != EXPECTED_PRODUCER or provenance.tool != EXPECTED_TOOL:
        avertissements.append(
            f"{WARN_PRODUCER_UNEXPECTED} : document déclaré produit par "
            f"{provenance.producer!r} / {provenance.tool!r}, attendu "
            f"{EXPECTED_PRODUCER!r} / {EXPECTED_TOOL!r}. Accepté — mais les "
            "mesures ne viennent pas du producteur de référence."
        )

    # Fraîcheur — indépendante de l'identité.
    lue = _parse_version(provenance.version)
    if lue is None:
        avertissements.append(
            f"{WARN_SOURCE_VERSION_UNKNOWN} : `source.version` absent ou illisible "
            f"({provenance.version!r}) — fraîcheur du document inconnue, mesures "
            "acceptées telles quelles."
        )
    elif lue < MIN_PRODUCER_VERSION:
        attendu = ".".join(str(n) for n in MIN_PRODUCER_VERSION)
        avertissements.append(
            f"{WARN_PRODUCER_BELOW_MINIMUM} : document produit par "
            f"{provenance.producer or '(producteur inconnu)'} {provenance.version}, "
            f"antérieur à {attendu}. Accepté car compatible — régénérer le "
            "document pour lever l'avertissement."
        )

    return provenance, tuple(avertissements)


def _is_finite_number(value: object) -> bool:
    """Un nombre réel exploitable — ni booléen, ni ``nan``, ni ``inf``.

    ``bool`` est exclu explicitement : en Python ``True`` est un ``int``, et
    ``opening_width_m: true`` passerait pour une largeur de 1 m.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _validate_shape_degraded(document: object, path: str) -> None:
    """Vérifications de **structure**, quand ``bim_core`` ne porte pas le contrat.

    Volontairement pauvre : c'est un garde-fou, pas une réimplémentation du
    schéma. Il attrape ce qui ferait planter la suite de façon illisible, et
    nomme le fichier fautif. Quand ``parse_spatial_evidence`` est disponible,
    c'est lui qui fait ce travail — cette fonction n'est alors pas appelée.

    Les champs **consommés**, eux, sont vérifiés dans les deux modes : voir
    :func:`_validate_consumed_fields`.
    """
    if not isinstance(document, dict):
        raise ValueError(f"{path} : objet JSON attendu, reçu {type(document).__name__}.")
    declared = document.get("schema")
    if declared != SCHEMA_SPATIAL_EVIDENCE:
        raise ValueError(f"{path} ne déclare pas {SCHEMA_SPATIAL_EVIDENCE} (schema={declared!r}).")
    for key in ("objects", "spaces"):
        value = document.get(key, [])
        if not isinstance(value, list):
            raise ValueError(f"{path} : `{key}` doit être une liste, reçu {type(value).__name__}.")
        for index, entry in enumerate(value):
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{path} : `{key}[{index}]` doit être un objet, reçu {type(entry).__name__}."
                )


def _validate_consumed_fields(document: dict, path: str) -> None:
    """Filtre local sur les champs consommés — appliqué dans **les deux modes**.

    Ce filtre ne double pas le contrat, il le complète là où le contrat ne
    tranche pas. Mesuré sur ``bim-core 0.4.0``, ``parse_spatial_evidence``
    **accepte** deux valeurs que le rapport ne doit pourtant jamais compter
    comme des mesures :

    - ``ifc_class: "  "`` — typé ``str`` sans contrainte de longueur. L'entrée
      serait comptée sous une classe vide et fausserait tous les ratios.
    - ``opening_width_m: true`` — en Python ``True`` est un ``int``, donc
      coercé en ``1.0``. Une largeur de porte de 1 m sortie d'un booléen.

    Ne pas rejouer ce filtre après la validation complète ferait donc
    **perdre** ces deux garde-fous au moment précis où le dépôt adopte
    ``bim-core>=0.4`` — une régression silencieuse, et sur l'axe qui compte :
    la fausse évaluabilité.

    Un champ **absent** ou ``null`` reste licite : c'est une mesure manquante,
    pas un document invalide, et c'est ce que le rapport doit pouvoir compter.
    """
    for key in ("objects", "spaces"):
        for index, entry in enumerate(document.get(key, []) or []):
            if isinstance(entry, dict):
                _validate_entry_fields(entry, f"{path} : `{key}[{index}]`")


def _validate_entry_fields(entry: dict, where: str) -> None:
    """Valide les champs consommés d'une entrée. Voir :func:`_validate_consumed_fields`."""
    ifc_class = entry.get("ifc_class")
    if not isinstance(ifc_class, str) or not ifc_class.strip():
        raise ValueError(f"{where}.ifc_class : chaîne non vide attendue, reçu {ifc_class!r}.")

    for field in _NUMERIC_FIELDS:
        if field not in entry or entry[field] is None:
            continue
        if not _is_finite_number(entry[field]):
            raise ValueError(
                f"{where}.{field} : nombre fini attendu, reçu {entry[field]!r} — "
                "une mesure absente doit être `null`, jamais une valeur non numérique."
            )

    bbox = entry.get("bbox")
    if bbox is None:
        return
    if not isinstance(bbox, dict):
        raise ValueError(f"{where}.bbox : objet attendu, reçu {type(bbox).__name__}.")
    missing = [k for k in _BBOX_KEYS if k not in bbox]
    if missing:
        raise ValueError(
            f"{where}.bbox : bornes manquantes {missing} — une boîte partielle "
            "ne mesure rien et serait comptée comme renseignée."
        )
    for k in _BBOX_KEYS:
        if not _is_finite_number(bbox[k]):
            raise ValueError(f"{where}.bbox.{k} : nombre fini attendu, reçu {bbox[k]!r}.")


def read_evidence(path: str) -> EvidenceFacts:
    """Lit un ``spatial_evidence/v1`` et relève ce qui y est effectivement rempli.

    **Chemin nominal** : ``audit-bim-mcp`` épingle ``bim-core>=0.4.0,<0.5``,
    donc ``parse_spatial_evidence`` est disponible et valide la structure du
    document — un document invalide doit être refusé ici plutôt que de fonder
    une couverture.

    ``_validate_shape_degraded`` est un **repli de compatibilité**, pour un
    environnement où ``bim-core`` serait absent ou antérieur à 0.4. Il fait
    alors les mêmes vérifications de structure, sinon un document étiqueté
    correctement mais absurde planterait sur un ``AttributeError`` illisible au
    lieu d'être refusé. Il ne remplace pas le contrat.

    Dans **les deux cas**, :func:`_validate_consumed_fields` s'applique ensuite :
    le contrat ne tranche ni un ``ifc_class`` vide ni un booléen coercé en
    nombre, et ces deux valeurs produiraient une fausse évaluabilité.
    """
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        from bim_core.contracts import parse_spatial_evidence
    except ImportError:
        _validate_shape_degraded(document, path)
    else:
        parse_spatial_evidence(document, origin=path)
    # Dans LES DEUX modes. Le contrat ne tranche ni `ifc_class` vide ni le
    # booléen coercé en nombre : ne pas rejouer ce filtre après la validation
    # complète ferait perdre ces garde-fous en adoptant bim-core>=0.4.
    _validate_consumed_fields(document, path)

    # Provenance : lue APRÈS la validation, et sans effet sur elle. Un document
    # invalide est déjà refusé ; une version ancienne n'est qu'un avertissement.
    provenance, avertissements = producer_warnings(document)

    counted: Counter[str] = Counter()
    filled: Counter[tuple[str, str]] = Counter()
    n_spaces_convex = n_spaces_with_width = 0

    for key in ("objects", "spaces"):
        for entry in document.get(key, []):
            ifc_class = entry.get("ifc_class") or "?"
            counted[ifc_class] += 1
            for field, value in entry.items():
                if value is not None:
                    filled[(ifc_class, field)] += 1
            if key == "spaces":
                rect = entry.get("min_rect_width_m")
                circle = entry.get("inscribed_diameter_m")
                if rect and circle:
                    n_spaces_with_width += 1
                    if circle / rect >= CONVEXITY_RATIO_MIN:
                        n_spaces_convex += 1

    return EvidenceFacts(
        schema=str(document.get("schema")),
        classes_present=frozenset(counted),
        filled=dict(filled),
        counted=dict(counted),
        n_spaces_convex=n_spaces_convex,
        n_spaces_with_width=n_spaces_with_width,
        provenance=provenance,
        warnings=avertissements,
    )


@dataclass(frozen=True)
class Assessment:
    """Ce qu'on pourra faire d'un contrôle, et pourquoi."""

    control: Control
    status: str
    rule: str | None
    reason: str


def _control_text(control: Control) -> str:
    """Texte normalisé du contrôle — même normalisation qu'en Domo-0."""
    return _normalize(f"{control.verification} {control.description}")


def metric_core(controls: list[Control]) -> list[Control]:
    """Le « noyau outillable » de Domo-0 : grandeur nommée + seuil chiffré, sans
    vocabulaire d'appréciation. Recalculé ici pour servir d'**auto-audit**."""
    return [
        c
        for c in controls
        if "needs_bbox" in c.signals and c.has_numeric_threshold and "manual_only" not in c.signals
    ]


def assess(control: Control, facts: EvidenceFacts) -> Assessment:
    """Statut d'un contrôle. L'ordre des tests EST la politique.

    L'appréciation prime sur tout : « il est recommandé que les boîtes aux
    lettres soient à l'intérieur du hall » porte une géométrie parfaitement
    mesurable, et reste une préférence du maître d'ouvrage. Trancher
    « non conforme » là-dessus contredirait son propre document.
    """
    text = _control_text(control)
    if _ADVISORY.search(text):
        return Assessment(control, "advisory_only", None, "vocabulaire d'appréciation")

    for rule in RULES:
        if not rule.matches(text):
            continue
        # Avant toute lecture de la maquette : si le contrat n'a pas de champ qui
        # mesure cette famille, aucun état du modèle ne peut rendre le contrôle
        # évaluable. Ce blocage prime donc sur la présence de la classe — dire
        # « classe absente » suggérerait qu'il suffirait de la modéliser.
        if rule.insufficient_reason:
            return Assessment(
                control, "non_evaluable_geometry_missing", rule.key, rule.insufficient_reason
            )
        if rule.ifc_class not in facts.classes_present:
            return Assessment(
                control,
                "non_evaluable_not_modeled",
                rule.key,
                f"{rule.ifc_class} absent du document de preuves",
            )
        if not facts.has_field(rule.ifc_class, rule.field):
            return Assessment(
                control,
                "non_evaluable_geometry_missing",
                rule.key,
                f"{rule.ifc_class}.{rule.field} renseigné sur 0 objet",
            )
        if rule.needs_convexity and facts.n_spaces_convex < facts.n_spaces_with_width:
            return Assessment(
                control,
                "non_evaluable_axis_required",
                rule.key,
                "largeur d'espace : exploitable seulement sur espace convexe "
                f"({facts.n_spaces_convex}/{facts.n_spaces_with_width}), "
                "axe médian requis sinon",
            )
        ratio = facts.fill_ratio(rule.ifc_class, rule.field)
        return Assessment(
            control,
            "evaluable_by_spatial_evidence",
            rule.key,
            f"{rule.ifc_class}.{rule.field} renseigné sur {ratio:.0%} des objets",
        )

    if _UNMODELLED.search(text):
        return Assessment(
            control,
            "non_evaluable_not_modeled",
            None,
            "objet de mobilier ou d'équipement, aucune classe IFC correspondante",
        )
    if control.has_numeric_threshold and "needs_space_context" in control.signals:
        return Assessment(
            control,
            "evaluable_with_object_mapping",
            None,
            "seuil chiffré et contexte spatial, mais l'objet visé reste à mapper",
        )
    return Assessment(control, "manual_review_required", None, "aucune règle applicable")


def surface_natures(tables) -> list[dict]:
    """Sépare les seuils indicatifs des seuils opposables.

    Les surfaces des deux tables sont légendées « souhaitable » par le maître
    d'ouvrage — « à titre indicatif » pour le collectif. Les ranger avec les
    ``LARGEUR MINI``, annoncées « dimension minimales », produirait des
    « non conforme » sur des valeurs que le client ne présente pas comme
    opposables.
    """
    natures: list[dict] = []
    for table in tables:
        caption = (table.caption or "").lower()
        advisory = "souhaitable" in caption or "indicatif" in caption
        natures.append(
            {
                "table": table.label,
                "nature": "surface_target_advisory" if advisory else "surface_target_unqualified",
                "portee": f"{len(table.room_types)} types × {len(table.typologies)} typologies",
                "legende": table.caption,
            }
        )
        natures.append(
            {
                "table": table.label,
                "nature": "width_min_mandatory" if table.has_width_column else "aucune",
                "portee": "colonne LARGEUR MINI" if table.has_width_column else "aucune",
                "legende": "annoncée « dimension minimales » dans la même légende",
            }
        )
    return natures


def print_report(assessments: list[Assessment], facts: EvidenceFacts, tables) -> None:
    by_status = Counter(a.status for a in assessments)
    distinct = {a.control.identity: a for a in assessments}
    by_status_distinct = Counter(a.status for a in distinct.values())

    print("DOCUMENT DE PREUVES")
    print(f"  schéma                     : {facts.schema}")
    # Le producteur RÉEL, jamais un nom supposé : afficher « ifc-geometry »
    # en dur présenterait un document tiers comme venant de notre producteur.
    print(
        f"  producteur                 : "
        f"{facts.provenance.label() if facts.provenance else '(inconnu)'}"
    )
    print(f"  classes présentes          : {len(facts.classes_present)}")
    print(
        f"  espaces convexes (≥ {CONVEXITY_RATIO_MIN:.2f}) : "
        f"{facts.n_spaces_convex} / {facts.n_spaces_with_width}"
    )

    # Avertissements de provenance. Aucun compteur n'en dépend : ils qualifient
    # d'où viennent les mesures, jamais ce qu'elles valent.
    for avertissement in facts.warnings:
        print(f"  /!\\ {avertissement}")

    controls = [a.control for a in distinct.values()]
    print()
    print("DIAGNOSTIC")
    print(f"  controls_total                  : {len(assessments)}")
    print(f"  logical_controls                : {len(distinct)}")
    core = {c.identity for c in metric_core(controls)}
    evaluable_in_core = sum(
        1
        for a in distinct.values()
        if a.status == "evaluable_by_spatial_evidence" and a.control.identity in core
    )
    print(f"  metric_rule_candidates          : {len(core)}   (noyau Domo-0)")
    print(f"  rules_claimed                   : {len(RULES)}   (registre)")
    # Deux dénominateurs, tous deux publiés. Le noyau Domo-0 est la base de
    # référence cadrée ; le total distinct compte en plus les contrôles qu'une
    # règle revendique sans qu'ils portent de seuil chiffré. N'en publier qu'un
    # ferait passer un changement de base pour un mouvement de couverture.
    print(f"  geometry_evaluable_in_core      : {evaluable_in_core} / {len(core)}   (base cadrée)")
    print(
        f"  geometry_evaluable_now          : "
        f"{by_status_distinct['evaluable_by_spatial_evidence']} / {len(distinct)}"
    )
    print(
        f"  geometry_blocked_axis_required  : {by_status_distinct['non_evaluable_axis_required']}"
    )
    print(
        f"  mapping_required                : {by_status_distinct['evaluable_with_object_mapping']}"
    )
    print(
        "  manual_or_judgement             : "
        f"{by_status_distinct['manual_review_required'] + by_status_distinct['advisory_only']}"
    )

    print()
    print("PAR STATUT — contrôles distincts / lignes du classeur")
    for status in STATUSES:
        print(f"  {status:32} {by_status_distinct[status]:4} {by_status[status]:4}")

    print()
    print("RÈGLES DU REGISTRE — ce que chacune revendique")
    for rule in RULES:
        claimed = sum(1 for a in distinct.values() if a.rule == rule.key)
        if rule.insufficient_reason:
            # Ne jamais afficher « disponible » pour une famille que le contrat
            # ne mesure pas : le champ peut être renseigné sans être la preuve.
            available = "INSUFFISANT (contrat)"
        elif facts.has_field(rule.ifc_class, rule.field):
            available = "disponible"
        else:
            available = "ABSENT du document"
        print(
            f"  {rule.key:24} {claimed:4} contrôles  {rule.ifc_class}.{rule.field:22} {available}"
        )

    print()
    print("SEUILS DU CLASSEUR — indicatifs vs opposables")
    for nature in surface_natures(tables):
        print(f"  {nature['table']:22} {nature['nature']:26} {nature['portee']}")

    print()
    print("AUTO-AUDIT — le noyau Domo-0 qu'aucune règle ne revendique")
    for assessment in sorted(distinct.values(), key=lambda a: a.control.row):
        if assessment.rule is None and assessment.control in metric_core(controls):
            print(
                f"  L{assessment.control.row:<4} {assessment.status:32} "
                f"{assessment.control.description[:60].replace(chr(10), ' ')}"
            )


def print_csv(assessments: list[Assessment]) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(
        ("row", "zone", "element", "verification", "description", "status", "rule", "reason")
    )
    for a in assessments:
        writer.writerow(
            [
                a.control.row,
                a.control.zone,
                a.control.element,
                a.control.verification,
                a.control.description,
                a.status,
                a.rule or "",
                a.reason,
            ]
        )
