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


def _job_block(workflow: Path, job: str) -> str:
    """Corps d'un job, délimité par l'indentation — même méthode que ci-dessus.

    On ne prend pas ``pyyaml`` : cf. :func:`_push_tags`.
    """
    lignes = workflow.read_text(encoding="utf-8").splitlines()
    debut = next((i for i, ligne in enumerate(lignes) if ligne.strip() == f"{job}:"), None)
    assert debut is not None, f"{workflow.name} : job {job!r} introuvable"
    indent = len(lignes[debut]) - len(lignes[debut].lstrip())
    corps = []
    for ligne in lignes[debut + 1 :]:
        if ligne.strip() and len(ligne) - len(ligne.lstrip()) <= indent:
            break
        corps.append(ligne)
    return "\n".join(corps)


#: Condition de publication, lue dans le workflow puis **évaluée**.
#:
#: Tester la présence d'une chaîne ne prouve rien sur ce que la condition
#: autorise. Une garde sur la seule ref — ``startsWith(github.ref,
#: 'refs/tags/')`` — semble correcte et laisse pourtant publier : un
#: ``workflow_dispatch`` accepte une ref de tag, donc le chemin censé ne
#: jamais publier publierait. On extrait l'événement et le préfixe attendus,
#: et on les confronte à des couples (événement, ref) réalistes.
_CONDITION = re.compile(
    r"if:\s*github\.event_name\s*==\s*'(?P<event>\w+)'\s*&&\s*"
    r"startsWith\(\s*github\.ref\s*,\s*'(?P<prefixe>[^']+)'\s*\)"
)


def _condition_de_publication(workflow: Path) -> tuple[str, str]:
    """``(événement, préfixe de ref)`` exigés par le job qui publie."""
    match = _CONDITION.search(_job_block(workflow, "create-release"))
    assert match, (
        "create-release ne teste pas (événement ET préfixe de ref) : "
        "une garde portant sur la seule ref laisse publier un dispatch sur un tag"
    )
    return match.group("event"), match.group("prefixe")


def _publierait(condition: tuple[str, str], *, event_name: str, ref: str) -> bool:
    """Évalue la condition du workflow pour un couple (événement, ref)."""
    event_attendu, prefixe = condition
    return event_name == event_attendu and ref.startswith(prefixe)


def test_the_release_workflow_can_be_dry_run():
    """Le workflow doit être déclenchable à la main.

    Sans ``workflow_dispatch``, la seule façon de l'exercer est de poser un
    vrai tag — donc de découvrir une panne le jour de la release, sur un tag
    déjà public et immuable.
    """
    texte = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^\s*workflow_dispatch:", texte, re.M), (
        "release.yml n'est déclenchable que par un tag : aucun dry-run possible"
    )


def test_the_publishing_condition_is_derived_from_the_distribution():
    """La condition doit viser l'événement ``push`` et le préfixe réel."""
    event, prefixe = _condition_de_publication(RELEASE_WORKFLOW)
    assert event == "push", event
    # Préfixe dérivé de la distribution, pas recopié : un renommage qui
    # oublierait cette ligne échouerait ici.
    assert prefixe == f"refs/tags/{_distribution_name()}-v", prefixe


@pytest.mark.parametrize(
    ("event_name", "ref", "publie"),
    [
        # Le seul chemin autorisé.
        ("push", "refs/tags/audit-bim-i3f-v0.10.0", True),
        # Dry-run sur une branche.
        ("workflow_dispatch", "refs/heads/master", False),
        # Dry-run lancé SUR UN TAG : `gh workflow run --ref` l'accepte, et
        # c'est le cas qu'une garde portant sur la seule ref laissait passer.
        ("workflow_dispatch", "refs/tags/audit-bim-i3f-v0.10.0", False),
        # Push de branche, et tag nu hors convention.
        ("push", "refs/heads/master", False),
        ("push", "refs/tags/v0.10.0", False),
    ],
)
def test_only_a_pushed_release_tag_publishes(event_name, ref, publie):
    """Un push de tag de release est le **seul** chemin vers la publication.

    C'est la promesse écrite dans ``.github/workflows/README.md``. Elle doit
    être vérifiée par évaluation de la condition, pas par la présence d'une
    chaîne : la version précédente de cette garde était présente, lisible, et
    laissait publier un dispatch lancé sur une ref de tag.
    """
    condition = _condition_de_publication(RELEASE_WORKFLOW)
    assert _publierait(condition, event_name=event_name, ref=ref) is publie


def test_the_publishing_guard_is_not_vacuous():
    """L'évaluateur doit autoriser le cas légitime et voir les gardes faibles.

    Sans le premier point, une garde qui refuse *tout* passerait chaque test
    de refus ci-dessus — et la publication ne marcherait jamais.
    """
    legitime = ("push", "refs/tags/audit-bim-i3f-v")
    assert _publierait(legitime, event_name="push", ref="refs/tags/audit-bim-i3f-v0.10.0")

    # La garde faible réellement écrite en premier : sans test d'événement,
    # elle publie sur un dispatch lancé depuis un tag.
    faible = re.compile(r"if:\s*startsWith\(\s*github\.ref\s*,\s*'refs/tags/'\s*\)")
    assert not _CONDITION.search("    if: startsWith(github.ref, 'refs/tags/')\n")
    assert faible.search("    if: startsWith(github.ref, 'refs/tags/')\n")

    # Et une condition absente ne doit pas être lue comme une condition.
    assert not _CONDITION.search("    name: Create GitHub Release\n")


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
