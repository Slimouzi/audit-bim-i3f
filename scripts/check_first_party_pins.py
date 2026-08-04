#!/usr/bin/env python3
"""Vérifie la cohérence des versions des paquets **first-party**.

Ces paquets ne sont pas sur PyPI : ils sont résolus par **tag Git immuable**, et
leur version apparaît à quatre endroits au moins — ``pyproject.toml``
(contrainte et tag), ``uv.lock``, les workflows CI/release, et le README. Rien
ne relie ces endroits entre eux.

C'est un piège éprouvé : ``release.yml`` a porté pendant des semaines une
génération de retard sur **chaque** brique, sans jamais échouer. Les bornes
larges rendaient les tags périmés silencieusement valides — la CI validait une
combinaison de dépendances, la release en construisait une autre. Le même motif
s'est reproduit avec un extra épinglé une version en arrière du tag publié.

Ce script transforme cette classe de dérive en échec de CI. Il vérifie que :

1. le **tag** déclaré dans ``[tool.uv.sources]`` satisfait la **contrainte** de
   version déclarée dans ``pyproject.toml`` ;
2. ``uv.lock`` référence **le même tag** ;
3. les workflows et le README ne citent **aucun autre tag** du même paquet ;
4. le paquet **installé** correspond au tag attendu (quand il est importable).

Usage : ``python scripts/check_first_party_pins.py [--root .] [--strict-installed]``
Sortie : 0 si tout concorde, 1 sinon, avec le détail de chaque écart.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

#: Paquets résolus par tag Git (jamais publiés sur PyPI).
FIRST_PARTY = (
    "bim-core",
    "bimdata-read",
    "bimdata-write",
    "bim-query",
    "bim-publication",
    "bim-audit-engine",
    "bim-reporting",
    "bim-mcp-runtime",
    "ifc-geometry-mcp",
)

#: Fichiers susceptibles de citer un tag, à garder alignés.
SCANNED_FILES = (
    ".github/workflows/ci.yml",
    ".github/workflows/release.yml",
    "README.md",
)

_TAG_VERSION = re.compile(r"-v(\d+(?:\.\d+)*)$")


def tag_version(tag: str) -> str | None:
    """Version portée par un tag ``<paquet>-v<X.Y.Z>``."""
    m = _TAG_VERSION.search(tag)
    return m.group(1) if m else None


def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split(".") if p.isdigit())


def satisfies(version: str, specifier: str) -> bool:
    """La version satisfait-elle un spécificateur simple (``>=``/``<``/``==``) ?

    Volontairement limité aux formes employées ici : les bornes de ce dépôt
    s'écrivent ``>=X.Y.Z,<A.B``. Un opérateur non géré est signalé plutôt
    qu'ignoré — un contrôle qui laisse passer ce qu'il ne comprend pas ne
    protège de rien.
    """
    cible = _parse_version(version)
    for clause in (c.strip() for c in specifier.split(",") if c.strip()):
        m = re.match(r"(>=|<=|==|<|>|!=)\s*([\d.]+)$", clause)
        if not m:
            raise ValueError(f"opérateur de version non géré : {clause!r}")
        op, brut = m.group(1), m.group(2)
        borne = _parse_version(brut)
        n = max(len(cible), len(borne))
        a = cible + (0,) * (n - len(cible))
        b = borne + (0,) * (n - len(borne))
        ok = {
            ">=": a >= b,
            "<=": a <= b,
            "==": a == b,
            "<": a < b,
            ">": a > b,
            "!=": a != b,
        }[op]
        if not ok:
            return False
    return True


def declared_specifiers(pyproject: dict[str, Any]) -> dict[str, str]:
    """Contraintes de version déclarées, dépendances **et** extras confondus."""
    projet = pyproject.get("project") or {}
    lignes: list[str] = list(projet.get("dependencies") or [])
    for extra in (projet.get("optional-dependencies") or {}).values():
        lignes.extend(extra)
    out: dict[str, str] = {}
    for ligne in lignes:
        m = re.match(r"^\s*([A-Za-z0-9._-]+)\s*(.*)$", ligne)
        if not m:
            continue
        nom, spec = m.group(1), m.group(2).strip()
        if nom in FIRST_PARTY and spec:
            out[nom] = spec
    return out


def declared_tags(pyproject: dict[str, Any]) -> dict[str, str]:
    """Tags Git déclarés dans ``[tool.uv.sources]``."""
    sources = ((pyproject.get("tool") or {}).get("uv") or {}).get("sources") or {}
    return {
        nom: src["tag"]
        for nom, src in sources.items()
        if nom in FIRST_PARTY and isinstance(src, dict) and src.get("tag")
    }


def locked_tags(lock: dict[str, Any]) -> dict[str, str]:
    """Tags effectivement verrouillés dans ``uv.lock``."""
    out: dict[str, str] = {}
    for paquet in lock.get("package") or []:
        nom = paquet.get("name")
        if nom not in FIRST_PARTY:
            continue
        url = ((paquet.get("source") or {}).get("git")) or ""
        m = re.search(r"[?&]tag=([^&#]+)", url)
        if m:
            out[nom] = m.group(1)
    return out


def referenced_tags(root: Path) -> dict[str, set[tuple[str, str]]]:
    """Tags cités dans les workflows et le README : ``{paquet: {(tag, fichier)}}``."""
    out: dict[str, set[tuple[str, str]]] = {nom: set() for nom in FIRST_PARTY}
    for rel in SCANNED_FILES:
        chemin = root / rel
        if not chemin.is_file():
            continue
        texte = chemin.read_text(encoding="utf-8")
        for nom in FIRST_PARTY:
            for m in re.finditer(rf"{re.escape(nom)}-v[\d.]+", texte):
                out[nom].add((m.group(0), rel))
    return out


def installed_version(nom: str) -> str | None:
    """Version du paquet réellement installé, ou ``None`` s'il est absent."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(nom)
    except PackageNotFoundError:
        return None


def check(root: Path, *, strict_installed: bool = False) -> list[str]:
    """Renvoie la liste des écarts. Vide = tout concorde."""
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock_path = root / "uv.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8")) if lock_path.is_file() else {}

    specs = declared_specifiers(pyproject)
    tags = declared_tags(pyproject)
    verrouilles = locked_tags(lock)
    cites = referenced_tags(root)

    ecarts: list[str] = []

    for nom, tag in sorted(tags.items()):
        version = tag_version(tag)
        if version is None:
            ecarts.append(f"{nom} : tag {tag!r} sans version reconnaissable (<paquet>-vX.Y.Z)")
            continue

        # 1. le tag satisfait-il la contrainte déclarée ?
        spec = specs.get(nom)
        if spec is None:
            ecarts.append(f"{nom} : tag {tag!r} déclaré mais aucune contrainte de version")
        else:
            try:
                if not satisfies(version, spec):
                    ecarts.append(
                        f"{nom} : le tag {tag!r} (version {version}) ne satisfait PAS "
                        f"la contrainte {spec!r} — pin hors borne"
                    )
            except ValueError as exc:
                ecarts.append(f"{nom} : {exc}")

        # 2. le lock pointe-t-il le même tag ?
        if lock_path.is_file():
            verrouille = verrouilles.get(nom)
            if verrouille is None:
                ecarts.append(f"{nom} : absent de uv.lock alors qu'il est déclaré")
            elif verrouille != tag:
                ecarts.append(
                    f"{nom} : uv.lock verrouille {verrouille!r} mais pyproject déclare {tag!r}"
                )

        # 3. les workflows / README citent-ils un autre tag ?
        for cite, fichier in sorted(cites.get(nom, set())):
            if cite != tag:
                ecarts.append(
                    f"{nom} : {fichier} cite {cite!r} au lieu de {tag!r} — "
                    "la CI et la release construiraient une autre combinaison"
                )

        # 4. le paquet installé correspond-il ?
        installee = installed_version(nom)
        if installee is None:
            if strict_installed:
                ecarts.append(f"{nom} : attendu en version {version}, non installé")
        elif _parse_version(installee) != _parse_version(version):
            ecarts.append(
                f"{nom} : version INSTALLÉE {installee} ≠ version du tag {version} "
                f"({tag!r}) — un pin correct ne dit rien de ce qui est installé"
            )

    return ecarts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="racine du dépôt")
    parser.add_argument(
        "--strict-installed",
        action="store_true",
        help="échouer aussi si un paquet first-party n'est pas installé",
    )
    args = parser.parse_args(argv)

    ecarts = check(Path(args.root), strict_installed=args.strict_installed)
    if ecarts:
        print("Incohérences de versions first-party :\n")
        for e in ecarts:
            print(f"  - {e}")
        print(
            "\nCes paquets sont résolus par tag Git immuable : une version citée à "
            "plusieurs endroits doit l'être partout à l'identique."
        )
        return 1
    print("Versions first-party cohérentes (pyproject / uv.lock / workflows / installé).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
