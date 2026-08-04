"""Contrats déclaratifs des profils clients/AMO.

Ces modèles ne pilotent pas encore le comportement du MCP. Ils forment un
inventaire versionnable : quelles briques sont génériques, quelles briques sont
spécifiques à un maître d'ouvrage, et ce qu'un nouveau MCP doit composer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ModuleStatus = Literal["externalized", "facade", "in_repo", "planned"]
SpecializationStatus = Literal["ready", "planned"]


@dataclass(frozen=True)
class GenericModule:
    """Brique réutilisable ou candidate à l'extraction."""

    key: str
    label: str
    current_location: str
    target_package: str
    status: ModuleStatus
    responsibility: str
    next_step: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "current_location": self.current_location,
            "target_package": self.target_package,
            "status": self.status,
            "responsibility": self.responsibility,
            "next_step": self.next_step,
        }


@dataclass(frozen=True)
class ClientSpecialization:
    """Ce qui doit rester dans un MCP enfant, propre au client final."""

    key: str
    label: str
    current_location: str | None
    status: SpecializationStatus
    responsibility: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "current_location": self.current_location,
            "status": self.status,
            "responsibility": self.responsibility,
        }


@dataclass(frozen=True)
class ReferenceFrameworkSpec:
    """Identité du référentiel contractuel d'un profil.

    Ce que le profil **nomme** ; la version et la source, elles, viennent du
    catalogue d'exigences chargé pour la mission. Séparer les deux est ce qui
    permet au socle narratif de ne plus citer aucun maître d'ouvrage.
    """

    name: str
    short_name: str
    long_name: str

    def to_dict(self) -> dict:
        return {"name": self.name, "short_name": self.short_name, "long_name": self.long_name}


@dataclass(frozen=True)
class ClassificationNarrativeSpec:
    """Systèmes de classification cités par les livrables d'un profil.

    Troisième axe du vocabulaire client, distinct du document contractuel et du
    maître d'ouvrage : « table interne 3F » n'est ni l'un ni l'autre, c'est un
    système propriétaire au même rang qu'UniFormat. Un scalaire
    ``default_classification_system`` ne suffit donc pas — il faut la liste des
    systèmes cités, et celui qui fait défaut.

    **Trois des quatre champs sont déclaratifs à ce stade** : seul
    ``default_system`` est lu. C'est assumé et testé (cf.
    ``test_report_narrative_spec``) plutôt que laissé ambigu — un champ de
    profil qu'on croit branché alors qu'il ne l'est pas est une fausse commande,
    et elle ne lève jamais.
    """

    #: Système appliqué par défaut. **Seul champ consommé à ce jour**
    #: (``context._build_controls_performed``).
    default_system: str
    #: Systèmes normalisés reconnus. DÉCLARATIF pour l'instant : aucun lecteur.
    #: Destinés à la structure Excel (PR C2) et au futur bim-classifier.
    known_systems: tuple[str, ...]
    #: Systèmes propriétaires du client. DÉCLARATIF, même raison.
    proprietary_systems: tuple[str, ...]
    #: Libellé imprimable du système propriétaire. DÉCLARATIF, même raison.
    proprietary_label: str

    def to_dict(self) -> dict:
        return {
            "default_system": self.default_system,
            "known_systems": list(self.known_systems),
            "proprietary_systems": list(self.proprietary_systems),
            "proprietary_label": self.proprietary_label,
        }


@dataclass(frozen=True)
class ReportNarrativeSpec:
    """Textes de livrable propres à un profil : méthode, sections, conseils.

    ``theme_hints`` est porté **entier**, pas troué. C'est un dict indexé par un
    énuméré générique (``Theme``, de bim-core) dont chaque valeur référence un
    chapitre du référentiel client : le paramétrer phrase par phrase donnerait
    une table à moitié substituée, moins lisible que l'original et impossible à
    relire d'un coup d'œil.
    """

    #: Recommandation corrective par thème d'audit. Clé = valeur de ``Theme``.
    theme_hints: dict[str, str]
    #: Phrase d'introduction de la section « Classification ».
    classification_intro: str
    #: Phrase d'introduction de la section « Conventions de nommage ».
    naming_intro: str
    #: Libellé du référentiel dans la liste des documents de référence.
    reference_documents_line: str
    #: Libellé de couverture pour la référence contractuelle.
    cover_reference_label: str
    #: Préfixe de la ligne « référentiel appliqué » de la section documents.
    applied_reference_label: str
    #: Recommandation transverse émise quand la conformité est faible.
    low_conformity_recommendation: str

    def to_dict(self) -> dict:
        return {
            "theme_hints": dict(self.theme_hints),
            "classification_intro": self.classification_intro,
            "naming_intro": self.naming_intro,
            "reference_documents_line": self.reference_documents_line,
            "cover_reference_label": self.cover_reference_label,
            "applied_reference_label": self.applied_reference_label,
            "low_conformity_recommendation": self.low_conformity_recommendation,
        }


@dataclass(frozen=True)
class ReportStructureSpec:
    """Éléments de **structure** du classeur Excel : noms d'onglets, en-têtes.

    Distincts du narratif, et à ne surtout pas confondre : une phrase se relit,
    un nom d'onglet est une **clé technique**. Un TCD, une macro ou un
    rapprochement côté maître d'ouvrage peuvent le référencer par son nom ; le
    changer casse un usage aval sans rien faire échouer chez nous. C'est
    pourquoi la recette de ces deux champs passe par l'ouverture du fichier
    produit, pas par une comparaison de texte.

    Le profil porte donc le nom **exact**, jamais une composition. Composer
    ``f"Référentiel {framework.name}"`` donnerait « Référentiel CCH BIM I3F »
    au lieu de « Référentiel I3F » — un gabarit différent, pour un gain nul.
    La composition reste possible pour un futur profil qui n'a pas d'historique
    à préserver.
    """

    #: En-tête de la colonne qui porte la référence au référentiel, dans les
    #: onglets de findings.
    finding_reference_column_label: str
    #: Nom exact de l'onglet de rappel du référentiel.
    referential_sheet_name: str

    def to_dict(self) -> dict:
        return {
            "finding_reference_column_label": self.finding_reference_column_label,
            "referential_sheet_name": self.referential_sheet_name,
        }


@dataclass(frozen=True)
class McpProfile:
    """Profil de composition d'un MCP client/AMO."""

    id: str
    label: str
    owner_name: str
    audience: str
    prompt_key: str
    default_catalog_label: str | None
    default_classification_system: str | None
    reference_framework: ReferenceFrameworkSpec | None
    report_narrative: ReportNarrativeSpec | None
    classification_narrative: ClassificationNarrativeSpec | None
    report_structure: ReportStructureSpec | None
    enabled_generic_modules: tuple[str, ...]
    specializations: tuple[ClientSpecialization, ...]
    report_packs: tuple[str, ...]
    #: Modules à importer pour enregistrer les outils du profil, **dans cet
    #: ordre**. Ce sont des chemins pointés, pas des objets : le registre est
    #: chargé au démarrage pour tous les profils, et importer les modules d'I3F
    #: pour lire la fiche de BIM in Motion enregistrerait les outils d'I3F.
    #: Un chemin faux ne peut pas passer inaperçu — cf. les tests qui vérifient
    #: que chaque module déclaré existe *et* déclare au moins un outil.
    tool_modules: tuple[str, ...] = ()
    #: Module exposant ``register_prompts(mcp)``. ``None`` = profil sans prompt.
    prompt_module: str | None = None
    #: Module des aliases LEGACY, importé seulement si l'opt-in est actif.
    legacy_alias_module: str | None = None
    notes: tuple[str, ...] = ()
    is_default: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "owner_name": self.owner_name,
            "audience": self.audience,
            "prompt_key": self.prompt_key,
            "default_catalog_label": self.default_catalog_label,
            "default_classification_system": self.default_classification_system,
            "reference_framework": (
                self.reference_framework.to_dict() if self.reference_framework else None
            ),
            "report_narrative": (
                self.report_narrative.to_dict() if self.report_narrative else None
            ),
            "classification_narrative": (
                self.classification_narrative.to_dict() if self.classification_narrative else None
            ),
            "report_structure": (
                self.report_structure.to_dict() if self.report_structure else None
            ),
            "enabled_generic_modules": list(self.enabled_generic_modules),
            "tool_modules": list(self.tool_modules),
            "prompt_module": self.prompt_module,
            "legacy_alias_module": self.legacy_alias_module,
            "specializations": [s.to_dict() for s in self.specializations],
            "report_packs": list(self.report_packs),
            "notes": list(self.notes),
            "is_default": self.is_default,
        }
