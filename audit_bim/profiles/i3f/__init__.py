"""Profil I3F — prompts, outils et aliases propres à ce maître d'ouvrage.

Ce package porte **l'expérience** du serveur : les noms d'outils, leur
granularité, leur enchaînement, le prompt AMO et les libellés. Rien de tout cela
n'est réutilisable par un autre AMO — c'est justement la raison de l'isoler.

``audit_bim/mcp`` ne garde que le bootstrap, le câblage et les adaptateurs
(session, sécurité, identité de modèle, phase, sélection). Un futur profil
déclarera ses propres modules ici, à côté, sans toucher au serveur.

**Aucun nom n'a changé au déplacement** : outils, prompt, aliases et paramètres
sont ceux d'avant, à l'octet près. Le contrôle est un dump MCP strict.
"""
