"""Modèle de contexte de rapport AMO BIM.

Concentre toutes les informations utiles à un rapport Word professionnel,
extraites de l'``AuditResult`` (snapshot + catalog + findings) **sans
inventer de données**. Si une information n'est pas disponible dans les
sources, elle est :

1. soit mise à ``None`` (les sections du Word affichent une mention
   « Information non disponible dans les documents fournis. ») ;
2. soit listée dans ``missing_information`` (pour la section dédiée à
   la fin du rapport).

Conception
----------

- **Pydantic v2 frozen** : modèle immuable, facile à sérialiser pour
  test / debug.
- **Pas de side-effect** : ``build_report_context`` est pure (lecture
  seule). Aucun appel API BIMData, aucune écriture.
- **Pas d'hallucination** : la fonction ne déduit jamais un MOA, une
  phase ou un objectif BIM absent des sources.
- **Multi-sources** : agrège ``snapshot.project``, ``snapshot.model``,
  ``snapshot.sites``, ``snapshot.buildings``, ``catalog`` (CCH +
  annexes), ``result.phase``, ``result.findings``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ..audit.engine import AuditResult


# ── Modèles ──────────────────────────────────────────────────────────────


class ControlDescription(BaseModel):
    """Description d'un contrôle réalisé par l'agent d'audit.

    Utilisé pour la section *Liste des contrôles réalisés* du rapport.
    Chaque entrée doit pouvoir s'afficher comme une ligne de tableau :
    Thème / Objectif / Données contrôlées / Source de la règle /
    Résultat synthétique.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    theme: str = Field(..., description="Thème métier (Hiérarchie spatiale, Nommage, ...).")
    objective: str = Field(..., description="Ce que le contrôle cherche à garantir.")
    checked_items: str = Field(..., description="Quels objets / valeurs sont vérifiés.")
    rule_source: str | None = Field(
        None,
        description=(
            "Document ou fichier qui porte la règle (chapitre CCH, "
            "annexe XLSX, code interne). None si la règle est implicite IFC."
        ),
    )
    severity_scope: str | None = Field(
        None,
        description="Niveau de sévérité maximum produit par ce contrôle (HIGH, MEDIUM…).",
    )


class ReportProjectContext(BaseModel):
    """Contexte projet enrichi consommé par le rapport Word.

    Les champs ``None`` ou listes vides indiquent une donnée manquante —
    le rapport doit afficher une mention « Information non disponible
    dans les documents fournis. » plutôt que de l'inventer.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    # ── Projet ──────────────────────────────────────────────────────────
    project_name: str | None = None
    model_name: str | None = None
    project_description: str | None = None
    project_phase: str | None = None
    client_name: str | None = None
    owner_name: str | None = None
    site_name: str | None = None
    building_name: str | None = None
    address: str | None = None

    # ── Référentiel ─────────────────────────────────────────────────────
    bim_reference: str | None = Field(
        None,
        description=(
            "Référentiel BIM appliqué (ex: 'CCH BIM I3F V3.6'). "
            "Construit depuis ``catalog.cch_version`` si disponible."
        ),
    )
    cch_version: str | None = None
    cch_source: str | None = None
    data_spec_source: str | None = None
    naming_spec_source: str | None = None

    # ── Attendus / objectifs ────────────────────────────────────────────
    expected_deliverables: list[str] = Field(default_factory=list)
    bim_objectives: list[str] = Field(default_factory=list)
    expected_uses: list[str] = Field(default_factory=list)

    # ── Contrôles ───────────────────────────────────────────────────────
    controls_performed: list[ControlDescription] = Field(default_factory=list)

    # ── Hypothèses et limites ───────────────────────────────────────────
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)

    # ── Métadonnées d'extraction ────────────────────────────────────────
    n_sites: int = 0
    n_buildings: int = 0
    n_storeys: int = 0
    n_spaces: int = 0
    n_zones: int = 0
    n_elements: int = 0
    n_findings: int = 0
    n_property_specs: int = 0
    n_naming_rules: int = 0

    # ── Auditeur (page de garde + section contexte) ─────────────────────
    auditor_name: str | None = Field(
        None,
        description=(
            "Nom de l'auditeur AMO à afficher sur la page de garde et "
            "dans le contexte de la mission. Fourni explicitement par "
            "l'utilisateur ; pas de valeur déduite."
        ),
    )

    # ── Traçabilité des sources de chaque champ ─────────────────────────
    # Mapping ``nom_du_champ → source`` parmi :
    #   - ``"user"`` : valeur fournie explicitement par l'utilisateur
    #     (tool MCP, CLI) — réputée fiable.
    #   - ``"extracted"`` : valeur extraite des sources documentaires /
    #     BIMData (snapshot.project, IfcSite, catalog) — réputée
    #     fiable mais sans validation explicite.
    #   - ``"deduced"`` : valeur déduite par heuristique (mots-clés,
    #     fallback) — à confirmer.
    #   - ``"missing"`` : valeur absente.
    #
    # Le rapport Word affiche un suffixe "(déduit — à confirmer)" pour
    # les champs en source ``"deduced"`` et — selon la sensibilité du
    # champ — pour les champs en source ``"extracted"``.
    field_sources: dict[str, str] = Field(
        default_factory=dict,
        description="Source par champ : 'user' / 'extracted' / 'deduced' / 'missing'.",
    )

    # ── Helper d'accès traçabilité ──────────────────────────────────────
    def source_of(self, field_name: str) -> str:
        """Renvoie la source d'un champ ('user' / 'extracted' /
        'deduced' / 'missing'). 'missing' par défaut."""
        return self.field_sources.get(field_name, "missing")


# ── Builders ─────────────────────────────────────────────────────────────


def _first_non_empty(*candidates) -> str | None:
    """Renvoie le premier élément non vide / non None.

    Une chaîne vide ou un dict vide compte comme "vide".
    """
    for c in candidates:
        if c is None:
            continue
        if isinstance(c, str):
            s = c.strip()
            if s:
                return s
        elif isinstance(c, (list, dict, tuple)):
            if c:
                return c if not isinstance(c, str) else c
        else:
            return c
    return None


def _extract_address(snapshot_project: dict, sites: list[dict]) -> str | None:
    """Tente d'extraire une adresse à partir du projet ou des sites.

    BIMData n'expose pas d'adresse standardisée — on cherche dans
    plusieurs champs candidats. Si aucune adresse n'est trouvée,
    retourne ``None`` (la fonction NE déduit JAMAIS une adresse à
    partir de noms).
    """
    # 1. Champs directs du projet (peu probable mais on tente)
    for key in ("address", "Adresse", "location", "Localisation"):
        val = snapshot_project.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # 2. Adresse au niveau du site (IFC IfcSite)
    for site in sites or []:
        for key in ("address", "Adresse", "long_name", "longname"):
            val = site.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _detect_bim_objectives_in_text(text: str) -> list[str]:
    """Cherche des objectifs BIM explicitement nommés dans un texte.

    On ne déduit pas : on cherche uniquement des **mots-clés** présents
    dans le texte source. Si rien n'est trouvé, retourne ``[]`` et le
    rapport mentionnera l'absence d'objectif BIM explicite.
    """
    if not text:
        return []
    tlow = text.lower()
    keywords = {
        "DOE numérique": ["doe numérique", "doe numerique", "dossier des ouvrages exécutés"],
        "Exploitation patrimoniale": ["exploitation patrimoniale", "patrimoine"],
        "Maintenance / GMAO": ["maintenance", "gmao", "gem"],
        "Gestion des surfaces": [
            "gestion des surfaces",
            "surfaces sh",
            "fiabilisation des surfaces",
        ],
        "Classification structurée": ["uniformat", "classification ifc", "omniclass"],
        "Coordination de modèles": ["coordination", "synthèse maquette"],
        "Détection de clashs": ["détection de clash", "clash detection"],
        "Quantitatifs / métré": ["quantitatif", "métré", "quantité de surface"],
        "Simulation thermique": ["simulation thermique", "stde", "rt2012", "re2020"],
    }
    found: list[str] = []
    for label, terms in keywords.items():
        for t in terms:
            if t in tlow:
                found.append(label)
                break
    return found


def _build_controls_performed(catalog) -> list[ControlDescription]:
    """Construit la liste descriptive des contrôles effectivement
    exécutés par l'agent ``audit_bim.audit.engine.run_audit``.

    Cette fonction reste **statique** (ne lit pas dynamiquement les
    modules de règles) car l'objectif est de donner au lecteur une vue
    explicite de ce que l'agent contrôle. Si une nouvelle règle est
    ajoutée à ``run_audit``, il faut aussi étendre cette liste.
    """
    cch_ref = "CCH BIM I3F"
    if catalog and catalog.cch_version:
        cch_ref = f"CCH BIM I3F V{catalog.cch_version}"

    return [
        ControlDescription(
            theme="Hiérarchie spatiale",
            objective=(
                "Vérifier la complétude et la cohérence Site → Bâtiment → "
                "Étage → Zone → Espace, et la présence des quantités "
                "spatiales (SHAB, SU)."
            ),
            checked_items="IfcSite, IfcBuilding, IfcBuildingStorey, IfcSpace, IfcZone",
            rule_source=f"{cch_ref}, chapitre 6.1",
        ),
        ControlDescription(
            theme="Nommage Site / Bâtiment / Étage",
            objective=(
                "Conformité aux conventions de codification I3F et aux "
                "listes fermées d'étages et de zones."
            ),
            checked_items=(
                "Attribut Name / LongName des Site, Building, BuildingStorey, Space, Zone."
            ),
            rule_source="Annexe « Nommage » (XLSX)",
        ),
        ControlDescription(
            theme="Classification IFC",
            objective=(
                "Présence d'une classification (UniFormat II par défaut) "
                "sur chaque élément requis et cohérence niveau 3."
            ),
            checked_items="Classifications associées via /classification-element",
            rule_source=f"{cch_ref}, chapitre 6.4",
        ),
        ControlDescription(
            theme="Propriétés attendues",
            objective=(
                "Présence et validité des Psets requis à la phase BIM auditée, par classe IFC."
            ),
            checked_items="Property sets et propriétés natives IFC",
            rule_source="Annexe « Spécifications » (XLSX)",
        ),
        ControlDescription(
            theme="Unicité / identifiants",
            objective=(
                "Identifiant équipement (Tag / Mark) renseigné et unique à partir de la phase DCE."
            ),
            checked_items="Attribut Tag / Mark sur les éléments concernés",
            rule_source=f"{cch_ref}, chapitre 6.2",
        ),
        ControlDescription(
            theme="Listes fermées (zones / pièces)",
            objective=("Couverture des typologies attendues (zones PC / PP, pièces du programme)."),
            checked_items="Zones et espaces présents vs liste catalogue",
            rule_source="Annexe « Nommage » + programme MOA",
        ),
        ControlDescription(
            theme="Quantités (surfaces, volumes)",
            objective=(
                "Présence des BaseQuantities (NetArea, GrossArea, "
                "NetVolume) sur les éléments quantifiables."
            ),
            checked_items="BaseQuantities IFC sur Slab, Wall, Space",
            rule_source="MVD IFC + CCH BIM I3F",
        ),
    ]


def _build_missing_information(ctx_data: dict, catalog, findings_count: int) -> list[str]:
    """Liste les informations *contextuelles* absentes (pas les
    findings — ceux-là sont déjà détaillés dans le corps du rapport).
    """
    missing: list[str] = []
    if not ctx_data.get("project_description"):
        missing.append(
            "Description du projet : non disponible dans les sources "
            "extraites (BIMData + documents MOA)."
        )
    if not ctx_data.get("client_name") and not ctx_data.get("owner_name"):
        missing.append(
            "Maîtrise d'ouvrage : non identifiée formellement dans les documents fournis."
        )
    if not ctx_data.get("address"):
        missing.append(
            "Adresse du projet : non renseignée sur l'IfcSite ni dans les métadonnées BIMData."
        )
    if not ctx_data.get("bim_objectives"):
        missing.append(
            "Objectifs BIM explicites : aucun objectif BIM nommément "
            "identifié dans les documents analysés."
        )
    if not ctx_data.get("expected_deliverables"):
        missing.append(
            "Livrables BIM attendus : non détaillés dans les documents "
            "analysés (au-delà des exigences du CCH)."
        )
    if catalog is None or not catalog.cch_source_pdf:
        missing.append("Cahier des Charges BIM (PDF) : non fourni ou non chargé.")
    if catalog is None or not catalog.data_spec_source:
        missing.append("Annexe « Spécifications des données » : non fournie ou non chargée.")
    if catalog is None or not catalog.naming_spec_source:
        missing.append("Annexe « Nommage » : non fournie ou non chargée.")
    if findings_count == 0:
        missing.append(
            "Findings : aucun finding détecté — vérifier que l'audit a bien été "
            "exécuté sur un snapshot non vide."
        )
    return missing


def build_report_context(result: AuditResult) -> ReportProjectContext:
    """Construit le :class:`ReportProjectContext` à partir d'un
    ``AuditResult``, **sans inventer de données**.

    Sources consultées :

    - ``result.snapshot.project`` (dict BIMData) — nom, description,
      éventuellement client / MOA.
    - ``result.snapshot.model`` (dict BIMData) — nom du modèle.
    - ``result.snapshot.sites`` / ``buildings`` — site, bâtiment,
      éventuellement adresse.
    - ``result.catalog`` — version CCH, sources documentaires,
      nombre d'exigences.
    - ``result.phase`` — phase BIM (APS / AVP / PRO / DCE / EXE / DOE /
      GESTION).

    Tout champ absent de ces sources reste ``None`` (et est consigné
    dans ``missing_information``).
    """
    snap = result.snapshot
    project = snap.project or {}
    model = snap.model or {}

    # ── Identité projet / modèle ────────────────────────────────────────
    project_name = _first_non_empty(project.get("name"), "—")
    if project_name == "—":
        project_name = None
    model_name = _first_non_empty(model.get("name"), "—")
    if model_name == "—":
        model_name = None

    project_description = _first_non_empty(
        project.get("description"),
        project.get("longname"),
        project.get("long_name"),
    )

    # Site / Bâtiment : 1er site / 1er bâtiment (cas mono-site fréquent).
    site_name: str | None = None
    building_name: str | None = None
    if snap.sites:
        first_site = snap.sites[0]
        site_name = _first_non_empty(
            first_site.get("name"), first_site.get("long_name"), first_site.get("longname")
        )
    if snap.buildings:
        first_building = snap.buildings[0]
        building_name = _first_non_empty(
            first_building.get("name"),
            first_building.get("long_name"),
            first_building.get("longname"),
        )

    address = _extract_address(project, snap.sites or [])

    # MOA / client : on ne tente PAS de déduire depuis le nom de
    # projet. Seul un champ explicite ``client`` / ``owner`` / ``moa``
    # sur le projet BIMData est utilisé.
    client_name = _first_non_empty(
        project.get("client"),
        project.get("owner"),
        project.get("moa"),
        project.get("maitre_ouvrage"),
    )
    owner_name = _first_non_empty(project.get("owner"), project.get("maitre_ouvrage"))

    # ── Référentiel ─────────────────────────────────────────────────────
    catalog = result.catalog
    cch_version = catalog.cch_version if catalog else None
    bim_reference = (
        f"CCH BIM I3F V{cch_version}" if cch_version else "CCH BIM I3F (version non précisée)"
    )

    # ── Objectifs BIM ───────────────────────────────────────────────────
    # On cherche dans la description projet d'éventuels mots-clés.
    # Si rien trouvé, la liste reste vide (et missing_information
    # signale l'absence).
    bim_objectives = _detect_bim_objectives_in_text(project_description or "")

    # ── Livrables / usages BIM ──────────────────────────────────────────
    # On ne déduit PAS — la liste reste vide tant que les documents
    # MOA n'ont pas été parsés pour extraire les livrables attendus.
    expected_deliverables: list[str] = []
    expected_uses: list[str] = []

    # ── Contrôles réalisés ──────────────────────────────────────────────
    controls = _build_controls_performed(catalog)

    # ── Hypothèses ──────────────────────────────────────────────────────
    assumptions: list[str] = []
    if cch_version:
        assumptions.append(
            f"Les exigences sont interprétées selon la version {cch_version} "
            "du CCH BIM I3F transmise au moment de l'audit."
        )
    assumptions.append(
        "Le périmètre audité est limité aux objets présents dans le "
        "snapshot BIMData au moment de l'extraction."
    )
    assumptions.append(
        "Les classifications, propriétés et matériaux audités sont ceux "
        "exposés par l'API BIMData ; un export IFC non complet peut donc "
        "produire des faux négatifs."
    )

    # ── Comptages ───────────────────────────────────────────────────────
    n_property_specs = len(catalog.properties) if catalog else 0
    n_naming_rules = len(catalog.naming_rules) if catalog else 0

    ctx_data = dict(
        project_name=project_name,
        model_name=model_name,
        project_description=project_description,
        project_phase=result.phase.value if result.phase else None,
        client_name=client_name,
        owner_name=owner_name,
        site_name=site_name,
        building_name=building_name,
        address=address,
        bim_reference=bim_reference,
        cch_version=cch_version,
        cch_source=catalog.cch_source_pdf if catalog else None,
        data_spec_source=catalog.data_spec_source if catalog else None,
        naming_spec_source=catalog.naming_spec_source if catalog else None,
        expected_deliverables=expected_deliverables,
        bim_objectives=bim_objectives,
        expected_uses=expected_uses,
        controls_performed=controls,
        assumptions=assumptions,
        n_sites=len(snap.sites or []),
        n_buildings=len(snap.buildings or []),
        n_storeys=len(snap.storeys or []),
        n_spaces=len(snap.spaces or []),
        n_zones=len(snap.zones or []),
        n_elements=len(snap.elements or []),
        n_findings=len(result.findings),
        n_property_specs=n_property_specs,
        n_naming_rules=n_naming_rules,
    )
    ctx_data["missing_information"] = _build_missing_information(
        ctx_data, catalog, len(result.findings)
    )

    # ── Renseigner field_sources ────────────────────────────────────────
    # Tout champ scalaire non None vient des sources documentaires
    # (snapshot.project, IfcSite, catalog). On les marque "extracted".
    # ``bim_objectives`` détectés via mots-clés sont "deduced".
    # ``project_phase`` vient explicitement de l'AuditResult — on le
    # traite comme "extracted" puisqu'il est fourni au moment du
    # ``run_audit`` ; un éventuel ``merge_user_context`` viendra
    # l'écraser en "user" si l'utilisateur le re-confirme.
    field_sources: dict[str, str] = {}
    extracted_candidates = [
        "project_name",
        "model_name",
        "project_description",
        "project_phase",
        "client_name",
        "owner_name",
        "site_name",
        "building_name",
        "address",
        "bim_reference",
        "cch_version",
        "cch_source",
        "data_spec_source",
        "naming_spec_source",
    ]
    for f in extracted_candidates:
        v = ctx_data.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            field_sources[f] = "missing"
        else:
            field_sources[f] = "extracted"
    # bim_objectives : déduits par heuristique (mots-clés)
    field_sources["bim_objectives"] = "deduced" if bim_objectives else "missing"
    # auditor_name : jamais renseigné par ``build_report_context``
    # (vient toujours du paramètre utilisateur via ``merge_user_context``).
    field_sources["auditor_name"] = "missing"
    ctx_data["field_sources"] = field_sources

    return ReportProjectContext(**ctx_data)


def merge_user_context(
    context: ReportProjectContext,
    *,
    project_address: str | None = None,
    project_phase: str | None = None,
    auditor_name: str | None = None,
    client_name: str | None = None,
    project_description: str | None = None,
) -> ReportProjectContext:
    """Fusionne des informations fournies par l'utilisateur dans un
    :class:`ReportProjectContext` existant.

    Pour chaque champ non ``None`` fourni :

    1. La valeur écrase celle du contexte initial.
    2. ``field_sources[<champ>]`` est mis à ``"user"`` (donc le rapport
       Word n'affichera **pas** la mention « déduit — à confirmer »).
    3. Le champ correspondant disparaît de ``missing_information`` si
       l'utilisateur a comblé le trou.

    Les champs non fournis (``None``) sont laissés tels quels — le
    contexte initial est respecté.

    Args:
        context: Contexte initial (typiquement issu de
            :func:`build_report_context`).
        project_address: Adresse du projet (à afficher dans la section
            *Description du projet*).
        project_phase: Phase BIM (APS/APD/PRO/DCE/EXE/DOE/GESTION).
            **Important** : ce champ ne ré-exécute pas l'audit ; il
            sert uniquement à confirmer la phase affichée dans le
            rapport. Si vous voulez auditer une autre phase, relancez
            ``full_audit`` avec un paramètre différent.
        auditor_name: Nom de l'auditeur (page de garde + section contexte).
        client_name: Maîtrise d'ouvrage (rare en MCP mais utile pour
            les rapports manuels).
        project_description: Description libre du projet (si la MOA
            préfère fournir un texte au lieu de laisser l'extracteur
            tenter de le deviner depuis BIMData).

    Returns:
        Nouveau ``ReportProjectContext`` (Pydantic frozen, donc copy).
    """
    updates: dict[str, object] = {}
    new_sources = dict(context.field_sources)

    user_inputs = {
        "address": project_address,
        "project_phase": project_phase,
        "auditor_name": auditor_name,
        "client_name": client_name,
        "project_description": project_description,
    }
    for field, value in user_inputs.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        updates[field] = value.strip() if isinstance(value, str) else value
        new_sources[field] = "user"

    if not updates:
        # Pas de modification réelle — on garde l'instance d'origine.
        return context

    updates["field_sources"] = new_sources

    # Nettoyer missing_information : retire les entrées correspondant
    # aux champs que l'utilisateur a comblés.
    filters = {
        "address": "Adresse du projet",
        "project_description": "Description du projet",
        "project_phase": "Phase BIM",  # peu probable d'apparaître, mais on filtre
        "auditor_name": "Auditeur",  # idem, jamais dans missing par défaut
        "client_name": "Maîtrise d'ouvrage",
    }
    keep: list[str] = []
    for entry in context.missing_information:
        skip = False
        for field, marker in filters.items():
            if field in updates and marker in entry:
                skip = True
                break
        if not skip:
            keep.append(entry)
    if keep != list(context.missing_information):
        updates["missing_information"] = keep

    return context.model_copy(update=updates)


__all__ = [
    "ControlDescription",
    "ReportProjectContext",
    "build_report_context",
    "merge_user_context",
]


# Helpers exposés pour réutilisation côté tests / debug
def _iter_non_empty(values: Iterable) -> list:
    return [v for v in values if v not in (None, "", [], {})]
