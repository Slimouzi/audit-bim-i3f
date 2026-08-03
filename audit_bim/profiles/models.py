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
class McpProfile:
    """Profil de composition d'un MCP client/AMO."""

    id: str
    label: str
    owner_name: str
    audience: str
    prompt_key: str
    default_catalog_label: str | None
    default_classification_system: str | None
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
            "enabled_generic_modules": list(self.enabled_generic_modules),
            "specializations": [s.to_dict() for s in self.specializations],
            "report_packs": list(self.report_packs),
            "notes": list(self.notes),
            "is_default": self.is_default,
        }
