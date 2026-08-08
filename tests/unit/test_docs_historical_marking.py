"""Une doc qui nomme l'ancienne distribution doit se déclarer historique.

Sans marquage, une trace de décision se relit comme une consigne courante. Le
danger n'est pas le nom périmé en lui-même : c'est qu'un lecteur suive un
document écrit pour un autre état du produit sans que rien ne l'en avertisse.

Deux régimes, et le contrôle force à choisir :

- **doc active** — elle nomme le produit tel qu'il s'appelle aujourd'hui ;
- **doc historique** — elle porte un bandeau qui le dit, et garde ses noms
  d'époque intacts, parce que les réécrire falsifierait la trace.

Le nom courant est **dérivé** de ``pyproject``, jamais recopié ici : un
renommage ultérieur fera échouer ce contrôle au lieu de le laisser mentir.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"

#: Marqueur exigé en tête d'une doc qui conserve des noms d'époque.
MARQUEUR = "Document historique"

#: Noms de distribution antérieurs, gelés. Cf. `test_release_trigger.py`, qui
#: applique le même principe aux namespaces de tags.
NOMS_ANTERIEURS = ("audit-bim-i3f",)


def _distribution_courante() -> str:
    texte = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^name = "([^"]+)"', texte, re.M)
    assert match, "prémisse : le pyproject doit déclarer un nom de distribution"
    return match.group(1)


def _mentions_hors_tag(texte: str, ancien: str) -> list[str]:
    """Mentions de l'ancien nom qui ne sont pas des noms de tag.

    ``audit-bim-i3f-v0.10.0`` désigne un tag réellement posé et immuable :
    le citer reste exact, y compris dans une doc courante.
    """
    return [
        m.group(0) for m in re.finditer(rf"{re.escape(ancien)}(-v[\d.]+)?", texte) if not m.group(1)
    ]


def _docs() -> list[Path]:
    return sorted(DOCS.glob("*.md"))


def test_the_docs_directory_is_not_empty():
    """Sentinelle : sans documents, tous les contrôles seraient vacants."""
    assert _docs(), "aucune doc trouvée — le contrôle ne prouverait rien"


@pytest.mark.parametrize("doc", _docs(), ids=lambda p: p.name)
def test_a_doc_naming_the_old_distribution_declares_itself_historical(doc):
    """Nommer l'ancien produit sans le dire est une consigne périmée."""
    texte = doc.read_text(encoding="utf-8")
    mentions = [m for ancien in NOMS_ANTERIEURS for m in _mentions_hors_tag(texte, ancien)]
    if not mentions:
        return
    entete = "\n".join(texte.splitlines()[:10])
    assert MARQUEUR in entete, (
        f"{doc.name} nomme {sorted(set(mentions))} sans bandeau « {MARQUEUR} » : "
        "soit c'est une doc active et le nom doit être corrigé, "
        "soit c'est une trace de décision et elle doit le déclarer"
    )


@pytest.mark.parametrize("doc", _docs(), ids=lambda p: p.name)
def test_a_historical_banner_names_the_current_distribution(doc):
    """Le bandeau doit dire vers quoi le nom a changé, sinon il informe à moitié."""
    texte = doc.read_text(encoding="utf-8")
    entete = "\n".join(texte.splitlines()[:10])
    if MARQUEUR not in entete:
        return
    assert _distribution_courante() in entete, (
        f"{doc.name} se déclare historique sans nommer la distribution courante "
        f"({_distribution_courante()!r})"
    )


def test_the_guard_is_not_vacuous():
    """Le contrôle doit distinguer les trois formes qu'il traite."""
    ancien = NOMS_ANTERIEURS[0]

    # Une mention nue est vue…
    assert _mentions_hors_tag(f"le paquet `{ancien}` expose…", ancien) == [ancien]
    # …et une citation de tag ne l'est pas : ces tags existent toujours.
    assert _mentions_hors_tag(f"le tag `{ancien}-v0.10.0` reste résolvable", ancien) == []
    # Le nom courant ne doit évidemment pas déclencher le contrôle.
    assert _mentions_hors_tag(f"la distribution `{_distribution_courante()}`", ancien) == []


def test_at_least_one_doc_is_actually_marked():
    """Non-vacuité d'ensemble : le marquage doit exister quelque part.

    Si plus aucune doc ne portait le bandeau, les contrôles ci-dessus
    passeraient tous — en ne protégeant plus rien.
    """
    marquees = [
        d.name
        for d in _docs()
        if MARQUEUR in "\n".join(d.read_text(encoding="utf-8").splitlines()[:10])
    ]
    assert marquees, "aucune doc marquée historique : le garde-fou est vacant"
