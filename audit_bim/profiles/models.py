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
    """

    default_system: str
    known_systems: tuple[str, ...]
    proprietary_systems: tuple[str, ...]
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
    enabled_generic_modules: tuple[str, ...]
    specializations: tuple[ClientSpecialization, ...]
    report_packs: tuple[str, ...]
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
            "enabled_generic_modules": list(self.enabled_generic_modules),
            "specializations": [s.to_dict() for s in self.specializations],
            "report_packs": list(self.report_packs),
            "notes": list(self.notes),
            "is_default": self.is_default,
        }
