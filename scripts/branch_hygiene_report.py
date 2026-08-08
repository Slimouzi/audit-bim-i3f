"""Rapport de branches et worktrees à nettoyer — **il ne supprime rien**.

``git branch --merged`` est inopérant ici : les PR sont **squash-mergées**, donc
le commit de la branche n'est jamais un ancêtre de ``master``. Une branche dont
tout le travail est publié apparaît donc « non mergée », et l'inverse est vrai
aussi : une branche jamais poussée peut sembler propre.

Le rapport croise donc trois sources, parce qu'aucune ne suffit :

1. l'état de la **PR** côté GitHub (source d'autorité sur « c'est parti ») ;
2. le **diff réel** avec ``master`` (``git cherry``) — ce qui reste porté par
   la branche et par elle seule ;
3. les **worktrees** attachés, qu'une suppression de branche casserait.

Usage :
    python scripts/branch_hygiene_report.py [--repo owner/name]
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} : {r.stderr.strip()}")
    return r.stdout


def _prs(repo: str) -> dict[str, dict]:
    """État des PR par branche source. Vide si ``gh`` est indisponible."""
    try:
        brut = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "-R",
                repo,
                "--state",
                "all",
                "--limit",
                "300",
                "--json",
                "number,state,headRefName",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if brut.returncode != 0:
            return {}
        return {p["headRefName"]: p for p in json.loads(brut.stdout or "[]")}
    except (OSError, ValueError):
        return {}


@dataclass
class Branche:
    nom: str
    pr: str
    commits_propres: int
    worktree: str | None
    verdict: str
    raison: str


def analyse(repo: str) -> list[Branche]:
    courante = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    prs = _prs(repo)
    worktrees: dict[str, str] = {}
    chemin = None
    for ligne in _git("worktree", "list", "--porcelain").splitlines():
        if ligne.startswith("worktree "):
            chemin = ligne.split(" ", 1)[1]
        elif ligne.startswith("branch ") and chemin:
            worktrees[ligne.split("/")[-1]] = chemin

    resultats: list[Branche] = []
    for nom in _git("branch", "--format=%(refname:short)").split():
        if nom == "master":
            continue
        # `git cherry` liste les commits de la branche SANS équivalent dans
        # master — les `-` sont déjà repris, y compris via un squash.
        sorties = _git("cherry", "master", nom).splitlines()
        propres = [ligne for ligne in sorties if ligne.startswith("+")]
        pr = prs.get(nom)
        etat_pr = f"#{pr['number']} {pr['state']}" if pr else "aucune PR"
        wt = worktrees.get(nom)

        if nom == courante:
            verdict, raison = "GARDER", "branche courante"
        elif wt:
            verdict, raison = "GARDER", f"worktree attaché : {wt}"
        elif pr and pr["state"] == "OPEN":
            verdict, raison = "GARDER", "PR ouverte"
        elif pr and pr["state"] == "MERGED":
            verdict, raison = "SUPPRIMABLE", "PR mergée (squash) — travail publié"
        elif pr and pr["state"] == "CLOSED":
            verdict, raison = "SUPPRIMABLE", "PR fermée sans merge — travail abandonné"
        elif not propres:
            verdict, raison = "SUPPRIMABLE", "aucun commit propre vs master"
        else:
            verdict, raison = "À VÉRIFIER", f"{len(propres)} commit(s) propres, aucune PR"

        resultats.append(Branche(nom, etat_pr, len(propres), wt, verdict, raison))
    return resultats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default="Slimouzi/audit-bim-mcp")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    args = ap.parse_args()

    lignes = analyse(args.repo)
    if args.json:
        print(json.dumps([b.__dict__ for b in lignes], ensure_ascii=False, indent=2))
        return 0

    ordre = {"À VÉRIFIER": 0, "SUPPRIMABLE": 1, "GARDER": 2}
    for b in sorted(lignes, key=lambda x: (ordre[x.verdict], x.nom)):
        print(f"  {b.verdict:12} {b.nom:38} {b.pr:16} {b.raison}")

    total = len(lignes)
    for v in ("À VÉRIFIER", "SUPPRIMABLE", "GARDER"):
        n = sum(1 for b in lignes if b.verdict == v)
        print(f"\n{v:12} : {n}/{total}")
    print(
        "\nAucune suppression effectuée. Les « À VÉRIFIER » portent du travail "
        "qu'aucune PR ne couvre : les regarder avant tout `git branch -D`."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
