"""Registre des profils MCP clients/AMO.

I3F reste le profil par défaut et le seul profil pleinement opérationnel dans
ce dépôt. BIM in Motion est déclaré comme prochain profil cible : il compose les
mêmes briques génériques, mais aucune spécialisation I3F ne lui est appliquée.
"""

from __future__ import annotations

from .models import ClientSpecialization, GenericModule, McpProfile

DEFAULT_PROFILE_ID = "i3f"

_GENERIC_MODULES: tuple[GenericModule, ...] = (
    GenericModule(
        key="extraction",
        label="Extraction BIMData / snapshot",
        current_location="audit_bim/extraction + bimdata-read",
        target_package="bimdata-read",
        status="externalized",
        responsibility="Lire BIMData, normaliser un ModelSnapshot et gérer le cache snapshot.",
        next_step="Conserver audit_bim/extraction comme façade ; ne pas y ajouter de règles client.",
    ),
    GenericModule(
        key="geometry",
        label="Calculs IFC OpenShell",
        current_location="ifc-geometry-mcp",
        target_package="ifc-geometry-mcp",
        status="externalized",
        responsibility="Calculer les BaseQuantities et les surfaces d'enveloppe depuis l'IFC.",
        next_step="Faire consommer les contrats JSON par les MCP enfants, jamais des XLS intermédiaires.",
    ),
    GenericModule(
        key="audit_engine",
        label="Moteur d'audit",
        current_location="audit_bim/audit/engine + bim-audit-engine",
        target_package="bim-audit-engine",
        status="externalized",
        responsibility="Orchestrer des règles injectées et agréger des findings déterministes.",
        next_step="Garder les règles client dans les profils enfants.",
    ),
    GenericModule(
        key="query",
        label="Requêtes et sélections",
        current_location="audit_bim/query + bim-query",
        target_package="bim-query",
        status="externalized",
        responsibility="Filtrer snapshots, findings et suggestions sans réseau ni écriture.",
        next_step="Les futurs MCP doivent réutiliser les presets génériques avant d'en ajouter.",
    ),
    GenericModule(
        key="bcf",
        label="BCF",
        current_location="audit_bim/bcf + bim-publication",
        target_package="bim-publication",
        status="externalized",
        responsibility="Transformer des findings en payloads BCF et plans d'écriture.",
        next_step="La poussée BIMData reste dans la façade MCP avec confirmation et journal.",
    ),
    GenericModule(
        key="smartview",
        label="Smart Views BIMData",
        current_location="audit_bim/smartview + bim-publication",
        target_package="bim-publication",
        status="externalized",
        responsibility="Transformer des sélections en vues partageables BIMData.",
        next_step="Mutualiser les styles de sélection, pas les libellés de campagne client.",
    ),
    GenericModule(
        key="classifier",
        label="Classification",
        current_location="audit_bim/classifier",
        target_package="bim-classifier",
        status="in_repo",
        responsibility="Lire catalogues de classification, suggérer et préparer les corrections.",
        next_step="Extraire après avoir séparé tables génériques et tables propres aux clients.",
    ),
    GenericModule(
        key="doe",
        label="DOE",
        current_location="audit_bim/doe",
        target_package="bim-doe",
        status="in_repo",
        responsibility="Extraire, rapprocher et préparer l'enrichissement DOE vers IFC/BIMData.",
        next_step="Séparer extracteurs de formats et règles de rapprochement client.",
    ),
    GenericModule(
        key="enrichment",
        label="Enrichissement données publiques",
        current_location="audit_bim/enrichment",
        target_package="bim-enrichment",
        status="in_repo",
        responsibility="Enrichir un projet avec BAN, PLU, DPE et Géorisques.",
        next_step="Isoler les connecteurs publics des attentes de reporting client.",
    ),
    GenericModule(
        key="reporting",
        label="Reporting Word / Excel / PDF / PPT",
        current_location="audit_bim/reporting",
        target_package="bim-reporting",
        status="in_repo",
        responsibility="Produire des livrables à partir de snapshots, findings et contrats JSON.",
        next_step="Extraire le socle de rendu ; garder les packs MOA dans les profils enfants.",
    ),
)

_ALL_GENERIC_KEYS = tuple(m.key for m in _GENERIC_MODULES)

_I3F_PROFILE = McpProfile(
    id="i3f",
    label="AMO BIM I3F",
    owner_name="I3F",
    audience="AMO BIM contrôlant des livrables CCH BIM I3F.",
    prompt_key="amo_bim_i3f",
    default_catalog_label="CCH BIM I3F V3.x",
    default_classification_system="UniFormat II",
    enabled_generic_modules=_ALL_GENERIC_KEYS,
    report_packs=("avp_i3f",),
    specializations=(
        ClientSpecialization(
            key="requirements_i3f",
            label="Catalogue CCH BIM I3F",
            current_location="audit_bim/requirements",
            status="ready",
            responsibility="Parser les annexes I3F et exposer RequirementsCatalog/BIMPhase.",
        ),
        ClientSpecialization(
            key="audit_rules_i3f",
            label="Règles d'audit I3F",
            current_location="audit_bim/audit/rules",
            status="ready",
            responsibility="Injecter les règles CCH I3F dans bim-audit-engine.",
        ),
        ClientSpecialization(
            key="report_pack_avp_i3f",
            label="Pack AVP I3F",
            current_location="audit_bim/reporting/avp",
            status="ready",
            responsibility="Produire les six annexes XLSX et le rapport Word selon le modèle I3F.",
        ),
        ClientSpecialization(
            key="prompt_i3f",
            label="Prompt AMO BIM I3F",
            current_location="audit_bim/mcp/prompts.py",
            status="ready",
            responsibility="Cadrer Claude sur le référentiel et le vocabulaire I3F.",
        ),
    ),
    notes=(
        "Profil par défaut : aucun comportement historique I3F ne change.",
        "Les templates MOA I3F servent de gabarits, jamais de source d'identité projet.",
    ),
    is_default=True,
)

_BIM_IN_MOTION_PROFILE = McpProfile(
    id="bim_in_motion",
    label="AMO BIM in Motion",
    owner_name="BIM in Motion",
    audience="AMO BIM préparant des audits et livrables sur mesure pour ses clients finaux.",
    prompt_key="amo_bim_in_motion",
    default_catalog_label=None,
    default_classification_system=None,
    enabled_generic_modules=_ALL_GENERIC_KEYS,
    report_packs=(),
    specializations=(
        ClientSpecialization(
            key="requirements_bim_in_motion",
            label="Référentiel client BIM in Motion",
            current_location=None,
            status="planned",
            responsibility="Brancher un référentiel par mission sans importer le CCH I3F.",
        ),
        ClientSpecialization(
            key="report_pack_bim_in_motion",
            label="Packs de rapports BIM in Motion",
            current_location=None,
            status="planned",
            responsibility="Composer Word, Excel, PDF et PPT depuis le socle reporting générique.",
        ),
        ClientSpecialization(
            key="prompt_bim_in_motion",
            label="Prompt AMO BIM in Motion",
            current_location=None,
            status="planned",
            responsibility="Décrire la posture AMO BIM in Motion et les questions de cadrage client.",
        ),
    ),
    notes=(
        "Profil préparatoire : il ne doit pas activer le pack AVP I3F.",
        "Le nouveau MCP doit dépendre des briques génériques, pas de audit-bim-i3f.",
    ),
)

_PROFILES: tuple[McpProfile, ...] = (_I3F_PROFILE, _BIM_IN_MOTION_PROFILE)


def list_generic_modules() -> tuple[GenericModule, ...]:
    """Renvoie le catalogue des briques réutilisables."""
    return _GENERIC_MODULES


def list_profiles() -> tuple[McpProfile, ...]:
    """Renvoie les profils client connus, I3F en premier."""
    return _PROFILES


def get_profile(profile_id: str) -> McpProfile:
    """Retourne un profil par identifiant, ou lève ``KeyError``."""
    normalized = (profile_id or "").strip().lower().replace("-", "_")
    for profile in _PROFILES:
        if profile.id == normalized:
            return profile
    raise KeyError(profile_id)


def profiles_payload(profile_id: str | None = None) -> dict:
    """Payload JSON-friendly exposé par le tool MCP."""
    selected = None
    profiles = list_profiles()
    if profile_id:
        selected = get_profile(profile_id)
        profiles = (selected,)
    return {
        "status": "ok",
        "default_profile_id": DEFAULT_PROFILE_ID,
        "profile_id": selected.id if selected else None,
        "generic_modules": [m.to_dict() for m in list_generic_modules()],
        "profiles": [p.to_dict() for p in profiles],
        "next_mcp_rule": (
            "Un MCP client compose les modules génériques et ajoute uniquement "
            "ses prompts, référentiels, règles et packs de rapports spécifiques."
        ),
    }
