"""Le code produit ne doit porter aucun chemin propre à un poste.

Un défaut « machine » ne se comporte pas comme une absence : il *ressemble* à
une configuration. Sur le poste d'origine il résout, partout ailleurs il
désigne un dossier inexistant — et le produit répond alors comme si la
configuration existait, ce qui est plus difficile à diagnostiquer qu'un
« non configuré » franc.

Cas éprouvé : ``avp_report_catalog`` portait
``/Users/stani/code/MCP/Documents maître d'ouvrage`` comme valeur par défaut de
``AVP_MOA_TEMPLATES_DIR``. Le remplacement est une **absence assumée** —
``moa_templates_dir()`` renvoie ``None`` tant que la variable n'est pas
déclarée.

Ce que ce contrôle ne vise **pas** : les docs, les exemples et les fixtures de
test, où un chemin de poste est une illustration légitime. Il ne porte que sur
``audit_bim/``, c'est-à-dire ce qui est livré.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PAQUET = REPO / "audit_bim"

#: Racines d'utilisateur propres à un poste. ``/tmp`` et ``/var`` en sont
#: exclus : ce sont des emplacements système, pas l'identité d'une machine.
_RACINES_MACHINE = re.compile(r"""["'](/Users/|/home/|[A-Z]:\\\\)""")


def _fichiers_produits() -> list[Path]:
    return sorted(p for p in PAQUET.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_package_ships_no_machine_specific_path():
    """Aucun littéral de chemin utilisateur dans ce qui est livré."""
    offenders = []
    for fichier in _fichiers_produits():
        for numero, ligne in enumerate(fichier.read_text(encoding="utf-8").splitlines(), 1):
            if _RACINES_MACHINE.search(ligne):
                offenders.append(f"{fichier.relative_to(REPO)}:{numero}: {ligne.strip()}")
    assert not offenders, "chemins propres à un poste dans le code livré :\n" + "\n".join(offenders)


def test_the_guard_is_not_vacuous():
    """Le contrôle doit reconnaître la forme réellement retirée, et elle seule."""
    # La ligne exacte qui existait avant ce lot.
    reel = """    os.getenv("AVP_MOA_TEMPLATES_DIR", "/Users/stani/code/MCP/Documents maître d'ouvrage")"""
    assert _RACINES_MACHINE.search(reel)
    assert _RACINES_MACHINE.search("""CHEMIN = '/home/ci/templates'""")

    # Et il ne doit pas crier sur ce qui est légitime : chemins relatifs,
    # emplacements système, ou simple mention en prose.
    for benin in (
        'Path("out") / "rapport.xlsx"',
        'tempfile.mkdtemp(dir="/tmp")',
        "# le dossier /Users/... du poste de dev n'est plus un défaut",
        'os.getenv("AVP_MOA_TEMPLATES_DIR")',
    ):
        assert not _RACINES_MACHINE.search(benin), benin


def test_the_moa_templates_dir_is_absent_unless_declared(monkeypatch):
    """Sans variable d'environnement, il n'y a pas de dossier — pas un défaut."""
    from audit_bim.reporting.avp_report_catalog import MOA_TEMPLATES_ENV, moa_templates_dir

    monkeypatch.delenv(MOA_TEMPLATES_ENV, raising=False)
    assert moa_templates_dir() is None

    monkeypatch.setenv(MOA_TEMPLATES_ENV, "/tmp/moa")
    assert moa_templates_dir() == Path("/tmp/moa")


def test_a_report_exposes_no_template_path_when_unconfigured(monkeypatch):
    """La conséquence côté sortie : aucun chemin exposé, jamais un chemin faux."""
    from audit_bim.reporting.avp_report_catalog import MOA_TEMPLATES_ENV, REPORT_SPECS

    assert REPORT_SPECS, "prémisse : le catalogue doit déclarer des rapports"
    spec = REPORT_SPECS[0]

    monkeypatch.delenv(MOA_TEMPLATES_ENV, raising=False)
    assert spec.template_path is None
    assert spec.resolved_template_path() is None

    # Déclaré mais vide : le chemin est calculé, et reste non résolu tant que le
    # fichier n'existe pas — c'est la distinction que le tool doit préserver.
    monkeypatch.setenv(MOA_TEMPLATES_ENV, "/tmp/moa-inexistant")
    assert spec.template_path == Path("/tmp/moa-inexistant") / spec.example_filename
    assert spec.resolved_template_path() is None


@pytest.mark.skipif(os.name == "nt", reason="chemins POSIX")
def test_a_declared_directory_resolves_a_real_template(tmp_path, monkeypatch):
    """Non-vacuité de la résolution : un fichier présent doit être exposé."""
    from audit_bim.reporting.avp_report_catalog import MOA_TEMPLATES_ENV, REPORT_SPECS

    spec = REPORT_SPECS[0]
    (tmp_path / spec.example_filename).write_text("x", encoding="utf-8")
    monkeypatch.setenv(MOA_TEMPLATES_ENV, str(tmp_path))

    assert spec.resolved_template_path() == str(tmp_path / spec.example_filename)
