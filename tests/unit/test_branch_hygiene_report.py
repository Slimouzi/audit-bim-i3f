"""Le rapport d'hygiène doit distinguer « pas de PR » de « je ne sais pas ».

Deux défauts éprouvés sur la première version, tous deux dans la zone où ce
script doit être fiable — il sert à décider quelles branches supprimer :

1. l'échec de ``gh`` était avalé et rendait un dictionnaire vide. Chaque
   branche s'affichait alors « aucune PR », c'est-à-dire une **affirmation**,
   alors que la source n'avait pas répondu. Sans accès GitHub, le rapport
   proposait donc de supprimer — ou de vérifier — sur la foi d'un silence ;
2. le nom de branche d'un worktree était réduit à son dernier segment.
   ``refs/heads/review/199`` devenait ``199``, donc la branche n'était pas
   reconnue comme attachée, et le rapport pouvait proposer de supprimer une
   branche dont un worktree dépend.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from branch_hygiene_report import (  # noqa: E402
    A_VERIFIER,
    GARDER,
    INDETERMINE,
    SUPPRIMABLE,
    lire_prs,
    verdict,
    worktrees_par_branche,
)

#: Sortie réelle de ``git worktree list --porcelain``, avec une branche à
#: slash — la forme qui cassait le découpage naïf.
PORCELAIN = """worktree /Users/stani/code/MCP/audit-bim-mcp
HEAD 78d3d8a4b4f0d7e9186f1e4cb9fce01d5c1dcff3
branch refs/heads/master

worktree /private/tmp/audit-bim-pr199
HEAD 2169100aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
branch refs/heads/review/199

worktree /private/tmp/audit-bim-pr198
HEAD 7c2465ea79f7682b75af716ab81c0c70c0d27e2f
detached
"""


def test_a_slashed_branch_is_recognised_as_attached():
    """``review/199`` doit être vue entière, pas réduite à ``199``."""
    trouve = worktrees_par_branche(PORCELAIN)

    assert trouve["review/199"] == "/private/tmp/audit-bim-pr199"
    assert "199" not in trouve, "le nom a été tronqué au dernier segment"
    assert trouve["master"] == "/Users/stani/code/MCP/audit-bim-mcp"


def test_a_detached_worktree_attaches_no_branch():
    """Un worktree détaché ne protège aucune branche — il n'en porte pas."""
    assert len(worktrees_par_branche(PORCELAIN)) == 2


def test_the_slashed_branch_is_protected_end_to_end():
    """Non-vacuité : la conséquence du bug, pas seulement son symptôme.

    Le découpage naïf ne rendait pas seulement un mauvais nom : il faisait
    tomber ``review/199`` dans une branche du classement qui propose de la
    supprimer.
    """
    attaches = worktrees_par_branche(PORCELAIN)
    v, raison = verdict(
        nom="review/199",
        courante="master",
        worktree=attaches.get("review/199"),
        pr=None,
        source_pr_disponible=True,
        commits_propres=2,
    )
    assert v == GARDER
    assert "worktree" in raison

    # Contre-épreuve : sans le worktree, la même branche demanderait un examen.
    v_sans, _ = verdict(
        nom="review/199",
        courante="master",
        worktree=None,
        pr=None,
        source_pr_disponible=True,
        commits_propres=2,
    )
    assert v_sans == A_VERIFIER


def test_an_unavailable_pr_source_yields_no_verdict():
    """Source PR muette : on ne conclut pas, et surtout pas « aucune PR »."""
    v, raison = verdict(
        nom="une-branche",
        courante="master",
        worktree=None,
        pr=None,
        source_pr_disponible=False,
        commits_propres=0,
    )
    assert v == INDETERMINE
    assert "indisponible" in raison

    # Le même cas, source disponible : là on peut conclure.
    v_dispo, _ = verdict(
        nom="une-branche",
        courante="master",
        worktree=None,
        pr=None,
        source_pr_disponible=True,
        commits_propres=0,
    )
    assert v_dispo == SUPPRIMABLE


def test_protection_wins_over_an_unavailable_source():
    """Ce qui protège doit primer : un worktree reste un worktree."""
    for nom, wt, attendu in (
        ("master", None, GARDER),
        ("review/199", "/private/tmp/audit-bim-pr199", GARDER),
    ):
        v, _ = verdict(
            nom=nom,
            courante="master",
            worktree=wt,
            pr=None,
            source_pr_disponible=False,
            commits_propres=3,
        )
        assert v == attendu, nom


@pytest.mark.parametrize(
    ("etat", "attendu"),
    [("OPEN", GARDER), ("MERGED", SUPPRIMABLE), ("CLOSED", SUPPRIMABLE)],
)
def test_a_known_pr_state_drives_the_verdict(etat, attendu):
    """Le squash-merge rend `git branch --merged` inopérant : la PR tranche."""
    v, _ = verdict(
        nom="une-branche",
        courante="master",
        worktree=None,
        pr={"number": 1, "state": etat},
        source_pr_disponible=True,
        commits_propres=5,
    )
    assert v == attendu


def test_lire_prs_returns_none_when_the_command_fails(monkeypatch):
    """``None``, jamais ``{}`` : l'un dit « je ne sais pas », l'autre affirme."""
    import subprocess

    class Echec:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Echec())
    assert lire_prs("owner/repo") is None

    class Absent:
        def __init__(self, *a, **k):
            raise FileNotFoundError("gh introuvable")

    monkeypatch.setattr(subprocess, "run", Absent)
    assert lire_prs("owner/repo") is None


def test_lire_prs_returns_a_mapping_when_the_command_succeeds(monkeypatch):
    """Non-vacuité : le chemin nominal doit bien produire une mesure."""
    import subprocess

    class Succes:
        returncode = 0
        stdout = '[{"number": 42, "state": "MERGED", "headRefName": "review/199"}]'

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Succes())
    prs = lire_prs("owner/repo")
    assert prs is not None
    assert prs["review/199"]["state"] == "MERGED"
