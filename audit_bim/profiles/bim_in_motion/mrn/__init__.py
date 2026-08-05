"""Grille de contrôle MRN — gabarit, exigences, et contrôles.

Livrable propre au profil BIM in Motion. Rien n'est importé du profil I3F : la
grille MRN et le CCH I3F sont deux référentiels distincts, et les faire
communiquer ferait entrer les règles de l'un dans le livrable de l'autre.
"""

from __future__ import annotations

from .template import MRNControlRow, MRNTemplate, parse_mrn_template

__all__ = ["MRNControlRow", "MRNTemplate", "parse_mrn_template"]
