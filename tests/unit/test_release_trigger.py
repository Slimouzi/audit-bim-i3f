"""Le déclencheur de `release.yml` doit matcher les tags réellement posés.

Panne éprouvée, et de la pire espèce : le workflow a écouté `tags: ["v*"]`
pendant que le dépôt taguait `audit-bim-i3f-vX.Y.Z` (namespace
historique, cf. `PREFIXE_HISTORIQUE`). Le glob ne matchait plus
rien, donc le workflow **ne partait pas** — et un workflow qui ne part pas
n'échoue jamais. Aucune CI rouge, aucune alerte : simplement plus aucune
GitHub Release depuis v0.8.0, sans que personne ne l'ait décidé.

Le contrôle ne compare pas à une chaîne écrite ici. Il **dérive** le préfixe
attendu du nom de la distribution : un renommage qui oublierait le trigger
échouerait donc, au lieu de reproduire silencieusement la même panne.
"""

from __future__ import annotations

import fnmatch
import os
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
        ("push", "refs/tags/audit-bim-mcp-v0.11.0", True),
        # Dry-run sur une branche.
        ("workflow_dispatch", "refs/heads/master", False),
        # Dry-run lancé SUR UN TAG : `gh workflow run --ref` l'accepte, et
        # c'est le cas qu'une garde portant sur la seule ref laissait passer.
        ("workflow_dispatch", "refs/tags/audit-bim-mcp-v0.11.0", False),
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
    legitime = ("push", "refs/tags/audit-bim-mcp-v")
    assert _publierait(legitime, event_name="push", ref="refs/tags/audit-bim-mcp-v0.11.0")

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


#: Namespaces de tags **antérieurs**, relevés sur le dépôt réel — pas devinés.
#:
#: Ils sont immuables et resteront résolvables : c'est l'historique, pas une
#: cible acceptable pour un futur tag. La liste est **close** : un quatrième
#: namespace qui apparaîtrait serait une dérive, pas une tolérance de plus.
#:
#: - ``v`` : convention d'origine, abandonnée — c'est elle qui a produit la
#:   panne du déclencheur (cf. docstring du module).
#: - ``audit-bim-i3f-v`` : convention intermédiaire, avant le renommage de
#:   distribution (lot B2).
PREFIXES_HISTORIQUES = ("audit-bim-i3f-v", "v")

#: Tag unique hors de toute convention, gelé tel quel.
TAGS_HORS_CONVENTION = ("legacy-i3f-mcp-v1.0",)

#: Compat : le namespace immédiatement précédent, celui que B2 remplace.
PREFIXE_HISTORIQUE = PREFIXES_HISTORIQUES[0]


def _tags_du_depot() -> list[str]:
    """Tags réellement posés. Liste vide si le clone n'en porte aucun."""
    import subprocess

    resultat = subprocess.run(
        ["git", "tag", "-l"], capture_output=True, text=True, cwd=REPO, timeout=60
    )
    assert resultat.returncode == 0, resultat.stderr
    return [t for t in resultat.stdout.split() if t]


def _tags_exigibles() -> list[str]:
    """Tags réels — et **en CI, leur absence est une erreur, pas un skip**.

    Panne mesurée sur la PR de renommage : ``actions/checkout`` fait par défaut
    un clone superficiel et **sans tags**. Les contrôles « confrontés aux tags
    réellement posés » se contentaient donc de ``skip``, et la CI était verte
    *parce qu'ils ne s'exécutaient pas*. Localement, où les tags existent, tout
    passait — l'écart était invisible des deux côtés.

    En CI on échoue donc explicitement, en nommant la cause : c'est ce qui
    empêche de réintroduire la vacuité en modifiant le checkout. Hors CI, le
    skip reste légitime : un clone superficiel de travail n'a rien à prouver.
    """
    tags = _tags_du_depot()
    if tags:
        return tags
    if os.environ.get("CI"):
        pytest.fail(
            "aucun tag dans le clone alors qu'on est en CI : le checkout doit "
            "déclarer `fetch-depth: 0`, sinon les contrôles confrontés aux tags "
            "réels sont vacants et la CI verdit sans rien vérifier"
        )
    pytest.skip("aucun tag local — rien à confronter")
    raise AssertionError("inatteignable")  # pragma: no cover


def _version(tag: str) -> tuple[int, ...]:
    """Clé de tri numérique — ``max()`` sur des chaînes classerait v0.9 > v0.10."""
    chiffres = re.search(r"v(\d+(?:\.\d+)*)$", tag)
    return tuple(int(n) for n in chiffres.group(1).split(".")) if chiffres else ()


def _dernier_tag_conventionnel(tags: list[str], courant: str) -> str | None:
    """Tag de version le plus récent, **parmi les namespaces conventionnels**.

    Les tags hors convention sont exclus, et pas par élégance : le dépôt porte
    ``legacy-i3f-mcp-v1.0``, dont la version ``1.0`` domine numériquement tout
    le versionnage réel du produit (``0.x``). Le laisser entrer ferait de lui
    le « dernier tag » pour toujours — et le contrôle du namespace exigerait
    qu'il commence par le préfixe courant. Il aurait donc cassé **au premier
    tag posé sous le nouveau nom**, c'est-à-dire au moment précis où il doit
    fonctionner.
    """
    prefixes = (courant, *PREFIXES_HISTORIQUES)
    candidats = [
        t for t in tags if _version(t) and t.startswith(prefixes) and t not in TAGS_HORS_CONVENTION
    ]
    return max(candidats, key=_version) if candidats else None


@pytest.mark.parametrize("prefixe", PREFIXES_HISTORIQUES)
def test_each_declared_historical_namespace_is_real(prefixe):
    """Chaque namespace historique déclaré doit exister dans ce dépôt.

    Sentinelle de la transition : un préfixe que plus aucun tag ne porte est
    une fiction, et la tolérance qu'on lui accorde devient un chèque en blanc.
    Ce contrôle a déjà servi — la première version de ce fichier déclarait
    **deux** namespaces alors que le dépôt en porte trois, prémisse écrite au
    lieu d'être mesurée.
    """
    tags = _tags_exigibles()
    assert [t for t in tags if t.startswith(prefixe) and _version(t)], (
        f"aucun tag ne porte {prefixe!r} : cette tolérance historique ne protège rien"
    )


def test_every_tag_belongs_to_a_known_namespace():
    """La liste des namespaces est **close** : un quatrième serait une dérive.

    Ce n'est pas de l'archéologie : tant que la liste est close et confrontée
    au dépôt, elle empêche qu'on règle un futur conflit de convention en
    ajoutant discrètement une tolérance de plus.
    """
    tags = _tags_exigibles()
    connus = (f"{_distribution_name()}-v", *PREFIXES_HISTORIQUES)
    inconnus = [
        t
        for t in tags
        if _version(t) and not t.startswith(connus) and t not in TAGS_HORS_CONVENTION
    ]
    assert not inconnus, f"tags hors des namespaces connus : {inconnus}"


def test_the_trigger_no_longer_matches_historical_tags():
    """**Le cœur de la transition.** Tolérer le passé ne l'autorise pas.

    Sans ce contrôle, la façon la plus simple de faire passer la suite au
    moment du renommage serait d'élargir le déclencheur aux deux namespaces —
    et le garde-fou deviendrait vacant : il n'exigerait plus rien du prochain
    tag. On vérifie donc que le glob capte le namespace **courant** et
    **refuse** l'ancien.
    """
    # TOUS les globs, pas seulement le premier. Le moyen le plus simple de
    # rendre ce contrôle vacant est d'ajouter une seconde entrée qui rouvre
    # l'ancien namespace : lire `globs[0]` ne la verrait jamais.
    globs = _push_tags(RELEASE_WORKFLOW)
    courant = f"{_distribution_name()}-v0.11.0"
    assert any(fnmatch.fnmatch(courant, g) for g in globs), f"{globs!r} ne capte pas {courant!r}"

    # Les contre-exemples viennent des tags RÉELLEMENT posés, pas d'échantillons
    # écrits ici : un contre-exemple inventé peut ne ressembler à rien de ce que
    # le dépôt porte.
    tags = _tags_exigibles()
    anciens = [
        t for t in tags if _version(t) and t.startswith(PREFIXES_HISTORIQUES) and t != courant
    ]
    assert anciens, "prémisse : le dépôt doit porter des tags historiques"
    captes = [(t, g) for t in anciens for g in globs if fnmatch.fnmatch(t, g)]
    assert not captes, f"le déclencheur capte encore des tags historiques : {captes}"


def test_the_next_tag_must_be_in_the_current_namespace():
    """Dit ce qui est attendu **ensuite**, pas seulement ce qui fut.

    Deux états possibles, et aucun n'est un laissez-passer :

    - transition **en cours** — aucun tag courant encore posé : on exige alors
      qu'il existe bien des tags historiques, sinon ce test ne prouverait rien ;
    - transition **consommée** — dès qu'un tag courant existe, le tag le plus
      récent du dépôt doit appartenir au namespace courant. Un retour à
      l'ancien namespace après le renommage serait une régression silencieuse.
    """
    tags = _tags_exigibles()
    courant = f"{_distribution_name()}-v"
    en_courant = [t for t in tags if t.startswith(courant)]

    if not en_courant:
        assert [t for t in tags if _version(t) and t.startswith(PREFIXES_HISTORIQUES)], (
            "ni tag courant ni tag historique : rien ne cadre le prochain tag"
        )
        return

    dernier = _dernier_tag_conventionnel(tags, courant)
    assert dernier is not None, "prémisse : au moins un tag conventionnel"
    assert dernier.startswith(courant), (
        f"le tag le plus récent est {dernier!r} : après le renommage, "
        f"le prochain tag attendu est {courant}X.Y.Z"
    )


def test_the_latest_tag_ignores_the_out_of_convention_tag():
    """Contre-épreuve du piège qui aurait cassé au premier tag du nouveau nom.

    ``legacy-i3f-mcp-v1.0`` porte une version ``1.0`` supérieure à tout le
    versionnage réel du produit (``0.x``). Sans exclusion, il serait le
    « dernier tag » pour toujours, et le contrôle exigerait qu'il commence par
    le préfixe courant — un échec garanti le jour où l'on pose
    ``audit-bim-mcp-v0.11.0``.
    """
    courant = f"{_distribution_name()}-v"
    apres_le_premier_tag = [
        "v0.8.0",
        "audit-bim-i3f-v0.10.0",
        "legacy-i3f-mcp-v1.0",
        f"{courant}0.11.0",
    ]
    assert _dernier_tag_conventionnel(apres_le_premier_tag, courant) == f"{courant}0.11.0"

    # Et le contrôle doit rester capable de voir une VRAIE régression :
    # un retour à l'ancien namespace après le renommage.
    regression = ["audit-bim-i3f-v0.12.0", "legacy-i3f-mcp-v1.0", f"{courant}0.11.0"]
    assert _dernier_tag_conventionnel(regression, courant) == "audit-bim-i3f-v0.12.0"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: str(p.relative_to(REPO)))
def test_documented_tag_commands_use_the_current_namespace(doc):
    """Ce qu'on lit avant de taguer doit nommer le namespace courant.

    Le lecteur d'une procédure ne vérifie pas le workflow : il copie la
    commande. Une commande restée sur l'ancien préfixe poserait un tag que le
    déclencheur ignore — la panne exacte que ce fichier existe pour empêcher.
    """
    if not doc.exists():
        pytest.skip(f"{doc.name} absent")
    courant = f"{_distribution_name()}-v"
    offenders = [
        ligne.strip()
        for ligne in doc.read_text(encoding="utf-8").splitlines()
        if re.search(r"git (tag|push origin)\b", ligne)
        and re.search(r"\baudit-bim-[\w.-]*v", ligne)
        and courant not in ligne
    ]
    assert not offenders, f"commande de tag sur un namespace périmé dans {doc.name} : {offenders}"


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
    for ligne in ("git tag -a audit-bim-mcp-vX.Y.Z", "git push origin audit-bim-mcp-v0.11.0"):
        assert not re.search(r"git (tag|push origin) v[X0-9]", ligne), ligne
