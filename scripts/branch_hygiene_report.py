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

**Si la source PR est indisponible, le rapport le dit et ne conclut pas.** Une
branche sans PR connue et une branche dont on n'a pas pu lire la PR ne sont pas
la même chose : les confondre transformerait un silence en mesure, et ferait
supprimer du travail publié — ou garder du bruit — pour de mauvaises raisons.

Usage :
    python scripts/branch_hygiene_report.py [--repo owner/name] [--json]

Code de sortie : ``0`` si la source PR a répondu, ``2`` si elle est
indisponible (le rapport reste lisible, mais aucun verdict n'engage).
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]

#: Verdicts possibles.
INDETERMINE = "INDÉTERMINÉ"
A_VERIFIER = "À VÉRIFIER"
SUPPRIMABLE = "SUPPRIMABLE"
GARDER = "GARDER"


def _git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} : {r.stderr.strip()}")
    return r.stdout


def worktrees_par_branche(porcelain: str) -> dict[str, str]:
    """``{branche: chemin}`` depuis ``git worktree list --porcelain``.

    Le nom de branche s'obtient en retirant **le seul préfixe ``refs/heads/``**.
    Découper sur ``/`` et garder le dernier segment réduirait
    ``refs/heads/review/199`` à ``199`` : la branche ne serait alors pas
    reconnue comme attachée, et le rapport proposerait de supprimer une branche
    dont un worktree dépend.
    """
    resultat: dict[str, str] = {}
    chemin: str | None = None
    for ligne in porcelain.splitlines():
        if ligne.startswith("worktree "):
            chemin = ligne.split(" ", 1)[1]
        elif ligne.startswith("branch ") and chemin:
            ref = ligne.split(" ", 1)[1].strip()
            resultat[ref.removeprefix("refs/heads/")] = chemin
    return resultat


def lire_prs(repo: str) -> dict[str, dict] | None:
    """PR par branche source, ou ``None`` si la source est **indisponible**.

    Le ``None`` est le point important : un dictionnaire vide dirait « aucune
    PR n'existe », ce qui est une affirmation. On ne peut pas la faire quand
    ``gh`` n'a pas répondu.
    """
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
    except (OSError, subprocess.SubprocessError):
        return None
    if brut.returncode != 0:
        return None
    try:
        return {p["headRefName"]: p for p in json.loads(brut.stdout or "[]")}
    except ValueError:
        return None


@dataclass
class Branche:
    nom: str
    pr: str
    commits_propres: int
    worktree: str | None
    verdict: str
    raison: str


@dataclass
class Rapport:
    branches: list[Branche] = field(default_factory=list)
    source_pr_disponible: bool = True


def verdict(
    *,
    nom: str,
    courante: str,
    worktree: str | None,
    pr: dict | None,
    source_pr_disponible: bool,
    commits_propres: int,
) -> tuple[str, str]:
    """Classement d'une branche. Fonction pure, pour être testable.

    L'ordre compte : ce qui protège (branche courante, worktree) passe avant
    l'indisponibilité de la source, qui passe avant tout verdict tiré de l'état
    d'une PR qu'on n'a pas pu lire.
    """
    if nom == courante:
        return GARDER, "branche courante"
    if worktree:
        return GARDER, f"worktree attaché : {worktree}"
    if not source_pr_disponible:
        return INDETERMINE, "source PR indisponible — aucun verdict possible"
    if pr and pr["state"] == "OPEN":
        return GARDER, "PR ouverte"
    if pr and pr["state"] == "MERGED":
        return SUPPRIMABLE, "PR mergée (squash) — travail publié"
    if pr and pr["state"] == "CLOSED":
        return SUPPRIMABLE, "PR fermée sans merge — travail abandonné"
    if not commits_propres:
        return SUPPRIMABLE, "aucun commit propre vs master"
    return A_VERIFIER, f"{commits_propres} commit(s) propres, aucune PR"


def analyse(repo: str) -> Rapport:
    courante = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
    prs = lire_prs(repo)
    disponible = prs is not None
    worktrees = worktrees_par_branche(_git("worktree", "list", "--porcelain"))

    rapport = Rapport(source_pr_disponible=disponible)
    for nom in _git("branch", "--format=%(refname:short)").split():
        if nom == "master":
            continue
        sorties = _git("cherry", "master", nom).splitlines()
        propres = [ligne for ligne in sorties if ligne.startswith("+")]
        pr = (prs or {}).get(nom)
        if not disponible:
            etat_pr = "source indispo."
        elif pr:
            etat_pr = f"#{pr['number']} {pr['state']}"
        else:
            etat_pr = "aucune PR"
        wt = worktrees.get(nom)
        v, raison = verdict(
            nom=nom,
            courante=courante,
            worktree=wt,
            pr=pr,
            source_pr_disponible=disponible,
            commits_propres=len(propres),
        )
        rapport.branches.append(Branche(nom, etat_pr, len(propres), wt, v, raison))
    return rapport


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default="Slimouzi/audit-bim-mcp")
    ap.add_argument("--json", action="store_true", help="sortie machine")
    args = ap.parse_args()

    rapport = analyse(args.repo)
    if args.json:
        print(
            json.dumps(
                {
                    "source_pr": "disponible" if rapport.source_pr_disponible else "indisponible",
                    "branches": [b.__dict__ for b in rapport.branches],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if rapport.source_pr_disponible else 2

    if not rapport.source_pr_disponible:
        print("source_pr = INDISPONIBLE — `gh` n'a pas répondu.")
        print(
            "Aucun verdict n'est rendu : « aucune PR » serait une affirmation "
            "que rien ne soutient.\n"
        )

    ordre = {INDETERMINE: 0, A_VERIFIER: 1, SUPPRIMABLE: 2, GARDER: 3}
    for b in sorted(rapport.branches, key=lambda x: (ordre[x.verdict], x.nom)):
        print(f"  {b.verdict:12} {b.nom:38} {b.pr:16} {b.raison}")

    total = len(rapport.branches)
    for v in (INDETERMINE, A_VERIFIER, SUPPRIMABLE, GARDER):
        n = sum(1 for b in rapport.branches if b.verdict == v)
        if n:
            print(f"\n{v:12} : {n}/{total}")
    print("\nAucune suppression effectuée.")
    if any(b.verdict == A_VERIFIER for b in rapport.branches):
        print(
            "Les « À VÉRIFIER » portent du travail qu'aucune PR ne couvre : "
            "les regarder avant tout `git branch -D`."
        )
    return 0 if rapport.source_pr_disponible else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
