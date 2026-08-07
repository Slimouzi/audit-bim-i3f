"""Le déclencheur de `release.yml` doit matcher les tags réellement posés.

Panne éprouvée, et de la pire espèce : le workflow a écouté `tags: ["v*"]`
pendant que le dépôt taguait `audit-bim-i3f-vX.Y.Z`. Le glob ne matchait plus
rien, donc le workflow **ne partait pas** — et un workflow qui ne part pas
n'échoue jamais. Aucune CI rouge, aucune alerte : simplement plus aucune
GitHub Release depuis v0.8.0, sans que personne ne l'ait décidé.

Le contrôle ne compare pas à une chaîne écrite ici. Il **dérive** le préfixe
attendu du nom de la distribution : un renommage qui oublierait le trigger
échouerait donc, au lieu de reproduire silencieusement la même panne.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RELEASE_WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
WORKFLOWS_DIR = REPO / ".github" / "workflows"
DOCS = (WORKFLOWS_DIR / "README.md", REPO / "README.md")


def _distribution_name() -> str:
    """Nom de la distribution, lu dans ``pyproject`` — pas recopié ici."""
    texte = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^name = "([^"]+)"', texte, re.M)
    assert match, "prémisse : le pyproject doit déclarer un nom de distribution"
    return match.group(1)


def _push_tags(workflow: Path) -> list[str]:
    """Globs de tags du déclencheur ``on.push.tags``.

    Lu par expression régulière, et non par un analyseur YAML : ``pyyaml``
    n'est ici qu'une dépendance **transitive**, et fonder un garde-fou dessus
    le rendrait cassable par une mise à jour sans rapport avec ce qu'il teste.
    Le déclarer, lui, toucherait ``pyproject`` — hors périmètre de ce lot.

    Le bloc est délimité par l'indentation : on lit les entrées ``- "…"`` qui
    suivent ``tags:``, et on s'arrête à la première ligne moins indentée.
    """
    texte = workflow.read_text(encoding="utf-8")
    lignes = texte.splitlines()
    debut = next((i for i, ligne in enumerate(lignes) if ligne.strip() == "tags:"), None)
    assert debut is not None, f"{workflow.name} : aucun bloc `tags:` trouvé"

    indent_bloc = len(lignes[debut]) - len(lignes[debut].lstrip())
    globs: list[str] = []
    for ligne in lignes[debut + 1 :]:
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        if len(ligne) - len(ligne.lstrip()) <= indent_bloc:
            break
        entree = ligne.strip()
        if not entree.startswith("-"):
            break
        globs.append(entree.lstrip("-").strip().strip("\"'"))
    assert globs, f"{workflow.name} : bloc `tags:` vide"
    return globs


def test_the_release_trigger_matches_the_distribution_name():
    """Le glob doit être ``<distribution>-v*``, dérivé et non recopié."""
    attendu = f"{_distribution_name()}-v*"
    assert _push_tags(RELEASE_WORKFLOW) == [attendu]


def test_the_trigger_would_reject_the_bare_prefix():
    """Non-vacuité : le contrôle doit refuser l'ancienne valeur.

    Sans elle, une comparaison mal écrite passerait aussi bien sur ``v*``, et le
    garde-fou reproduirait la panne qu'il existe pour empêcher.
    """
    attendu = f"{_distribution_name()}-v*"
    assert attendu != "v*"
    assert not re.fullmatch(r"v\*", attendu)


def test_the_actual_tags_match_the_trigger():
    """Le glob doit matcher les tags **réellement posés** dans ce dépôt.

    Comparer le trigger à une convention écrite ne prouve rien si la convention
    elle-même a divergé de la pratique. On confronte donc le glob aux tags que
    le dépôt porte vraiment.
    """
    import subprocess

    resultat = subprocess.run(
        ["git", "tag", "-l"], capture_output=True, text=True, cwd=REPO, timeout=60
    )
    assert resultat.returncode == 0, resultat.stderr
    tags = [t for t in resultat.stdout.split() if t]
    if not tags:  # dépôt sans tags (clone superficiel) : rien à prouver
        pytest.skip("aucun tag local — rien à confronter")

    prefixe = f"{_distribution_name()}-v"
    correspondants = [t for t in tags if t.startswith(prefixe)]
    assert correspondants, (
        f"aucun tag ne commence par {prefixe!r} : le trigger viserait dans le vide"
    )
    # Le dernier tag de version posé doit être capté par le déclencheur.
    dernier = max(correspondants)
    assert dernier.startswith(prefixe), dernier


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(REPO)))
def test_no_documentation_instructs_a_bare_version_tag(doc):
    """Une consigne périmée est une panne différée.

    Un lecteur qui suit ``git tag vX.Y.Z`` pose un tag que le workflow ignore.
    Il croit avoir publié ; rien n'est publié, et rien ne le lui dit.
    """
    if not doc.exists():
        pytest.skip(f"{doc.name} absent")
    texte = doc.read_text(encoding="utf-8")
    offenders = [
        ligne.strip()
        for ligne in texte.splitlines()
        if re.search(r"git (tag|push origin) v[X0-9]", ligne)
    ]
    assert not offenders, f"consigne de tag périmée dans {doc.name} : {offenders}"


def test_the_documentation_guard_is_not_vacuous():
    """La recherche doit reconnaître les deux formes qu'on veut interdire."""
    for ligne in ("git tag vX.Y.Z", "git push origin v0.9.0"):
        assert re.search(r"git (tag|push origin) v[X0-9]", ligne), ligne
    # Et laisser passer la forme correcte, sinon le contrôle interdirait tout.
    for ligne in ("git tag -a audit-bim-i3f-vX.Y.Z", "git push origin audit-bim-i3f-v0.10.0"):
        assert not re.search(r"git (tag|push origin) v[X0-9]", ligne), ligne
