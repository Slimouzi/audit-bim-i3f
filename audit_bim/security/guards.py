"""Gardes partagées des runners de ``scripts/`` — **module produit** (PR4 §4a).

Vit dans le package installé (pas ``scripts/_guards.py``) : les runners sont chargés
**par chemin** dans les tests (``importlib``), donc un module sibling poserait un
problème de ``sys.path`` ; le package installé n'en pose aucun.

Deux gardes, dédupliquées depuis les 4 runners :
 - :func:`assert_outside_repo` — refuse d'écrire plans/sorties DANS le dépôt (ils
   peuvent porter des données client — écrire hors repo) ;
 - :func:`assert_catalog_usable` — refuse un référentiel CCH inexploitable
   (documents absents ou catalogue vide) qui rendrait un verdict faussement PASS.
"""

from __future__ import annotations

from pathlib import Path


def assert_outside_repo(path: Path | str, *, context: str) -> None:
    """Refuse (``SystemExit``) si ``path`` est **dans** le dépôt Git courant.

    Les plans scellés / sorties des runners peuvent porter des données client :
    ils doivent être écrits **hors du dépôt**. Le message est contextualisé par
    ``context`` (nom du runner / de l'artefact). Si aucun dépôt Git n'est détecté
    (package installé hors arbre de dev), il n'y a rien à protéger → no-op.
    """
    root = Path(__file__).resolve()
    while root != root.parent and not (root / ".git").exists():
        root = root.parent
    if not (root / ".git").exists():
        return  # pas de dépôt Git (package installé) → rien à confiner
    target = Path(path).resolve()
    if target == root or root in target.parents:
        raise SystemExit(
            f"REFUS ({context}) : {target} est dans le dépôt {root}. Les plans/sorties "
            f"peuvent porter des données client — écris-les HORS du repo (ex. /tmp)."
        )


def assert_catalog_usable(docs: dict[str, str | None], catalog) -> None:
    """Refuse (``SystemExit``) un référentiel CCH inexploitable — **helper pur**.

    ``build_catalog`` tolère des documents absents et rend un catalogue
    partiel/vide ; sans contrôle, un runner pourrait rendre ``PASS`` sans aucun
    référentiel CCH réellement chargé. On refuse si :

    - un des documents I3F (``docs`` = nom → chemin) est absent/introuvable ;
    - ``catalog.properties`` ou ``catalog.naming_rules`` est vide.
    """
    missing = [name for name, p in docs.items() if not p or not Path(p).exists()]
    if missing:
        raise SystemExit(f"REFUS : documents I3F absents {missing} — contrôle CCH impossible.")
    n_props = len(getattr(catalog, "properties", None) or [])
    n_rules = len(getattr(catalog, "naming_rules", None) or [])
    if n_props == 0 or n_rules == 0:
        raise SystemExit(
            f"REFUS : catalogue CCH vide (properties={n_props}, naming_rules={n_rules}) "
            f"— exécution non fiable."
        )
