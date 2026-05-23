"""Agent BCF — produit des Topics BCF 2.1 (issues à résoudre).

Un BCF Topic = une *issue* avec workflow : assignation, statut (Open / In
Progress / Closed), priorité, commentaires, description riche. Apparaît
dans le panneau **BCF Issues** du viewer BIMData. Format buildingSMART
standard, donc portable hors BIMData.

Pour des *vues 3D rapides* (sans workflow d'issue), préférer l'agent
``audit_bim.smartview`` (panneau Smart Views du viewer).
"""
from .builder import build_bcf_payloads, push_bcf_topics

__all__ = ["build_bcf_payloads", "push_bcf_topics"]
