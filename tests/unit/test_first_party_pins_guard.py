"""Le garde-fou de versions first-party attrape-t-il les dérives réelles ?

Chaque cas testé ici correspond à une dérive **effectivement survenue** dans ce
dépôt :

- ``release.yml`` a porté une génération de retard sur chaque brique, sans
  jamais échouer — les bornes larges rendaient les tags périmés valides ;
- l'extra ``geometry`` a épinglé une version en arrière du tag publié ;
- un paquet installé peut différer du pin, un `pyproject.toml` correct ne
  disant rien de ce qui est réellement dans l'environnement.

Un garde-fou qui ne reproduit pas ces cas ne protège de rien.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_first_party_pins import (  # noqa: E402
    check,
    satisfies,
    tag_version,
)

PYPROJECT = """
[project]
name = "audit-bim-i3f"
version = "0.8.0"
dependencies = [
    "requests>=2.31,<3",
    "bim-core{core_spec}",
]

[project.optional-dependencies]
geometry = [
    "ifc-geometry-mcp{geo_spec}",
]

[tool.uv.sources]
bim-core = {{ git = "https://github.com/Slimouzi/bim-core.git", tag = "{core_tag}" }}
ifc-geometry-mcp = {{ git = "https://github.com/Slimouzi/ifc-geometry-mcp.git", tag = "{geo_tag}" }}
"""

LOCK = """
[[package]]
name = "bim-core"
version = "0.3.0"
source = {{ git = "https://github.com/Slimouzi/bim-core.git?tag={core_tag}#abc123" }}

[[package]]
name = "ifc-geometry-mcp"
version = "0.3.0"
source = {{ git = "https://github.com/Slimouzi/ifc-geometry-mcp.git?tag={geo_tag}#def456" }}
"""

WORKFLOW = """
name: CI
jobs:
  test:
    steps:
      - run: pip install "git+https://github.com/Slimouzi/bim-core.git@{core_tag}"
"""


@pytest.fixture
def depot(tmp_path):
    """Fabrique un dépôt minimal ; chaque paramètre peut être désaccordé."""

    def _build(
        *,
        core_spec=">=0.3.0,<0.4",
        core_tag="bim-core-v0.3.0",
        geo_spec=">=0.3.0,<0.4",
        geo_tag="ifc-geometry-mcp-v0.3.0",
        lock_core_tag=None,
        workflow_core_tag=None,
        avec_lock=True,
        avec_workflow=True,
    ):
        (tmp_path / "pyproject.toml").write_text(
            PYPROJECT.format(
                core_spec=core_spec, core_tag=core_tag, geo_spec=geo_spec, geo_tag=geo_tag
            ),
            encoding="utf-8",
        )
        if avec_lock:
            (tmp_path / "uv.lock").write_text(
                LOCK.format(core_tag=lock_core_tag or core_tag, geo_tag=geo_tag),
                encoding="utf-8",
            )
        if avec_workflow:
            wf = tmp_path / ".github" / "workflows"
            wf.mkdir(parents=True, exist_ok=True)
            (wf / "ci.yml").write_text(
                WORKFLOW.format(core_tag=workflow_core_tag or core_tag), encoding="utf-8"
            )
        return tmp_path

    return _build


def _ecarts(chemin) -> list[str]:
    # ``strict_installed=False`` : la fixture ne prétend pas installer ces
    # paquets. Le contrôle « installé » a son propre test.
    return check(Path(chemin), strict_installed=False)


# ── tout concorde ──────────────────────────────────────────────────────


def test_coherent_repo_passes(depot):
    ecarts = _ecarts(depot())
    # Les seuls écarts admissibles portent sur la version installée, qui n'est
    # pas celle de la fixture (bim-core réel = 0.2.0 dans cet environnement).
    assert all("INSTALLÉE" in e for e in ecarts), ecarts


# ── dérive 1 : pin hors borne (le cas de l'extra geometry) ─────────────


def test_tag_outside_its_own_constraint_is_caught(depot):
    """Tag v0.2.0 déclaré alors que la contrainte exige >=0.3.0."""
    chemin = depot(geo_spec=">=0.3.0,<0.4", geo_tag="ifc-geometry-mcp-v0.2.0")
    ecarts = [e for e in _ecarts(chemin) if "ifc-geometry-mcp" in e]

    assert any("ne satisfait PAS" in e and "hors borne" in e for e in ecarts), ecarts


def test_wide_bound_still_catches_stale_tag_via_lock(depot):
    """Bornes larges : le tag périmé reste « valide », mais le lock le trahit.

    C'est exactement ce qui rendait la dérive de ``release.yml`` invisible.
    """
    chemin = depot(
        core_spec=">=0.1.0,<0.4",  # borne large : v0.1.1 la satisfait
        core_tag="bim-core-v0.1.1",
        lock_core_tag="bim-core-v0.3.0",
    )
    ecarts = [e for e in _ecarts(chemin) if "bim-core" in e]

    assert any("uv.lock verrouille" in e for e in ecarts), ecarts


# ── dérive 2 : workflow en retard (le cas release.yml) ─────────────────


def test_workflow_citing_another_tag_is_caught(depot):
    """Le workflow installe une autre version que celle déclarée."""
    chemin = depot(core_tag="bim-core-v0.3.0", workflow_core_tag="bim-core-v0.1.1")
    ecarts = [e for e in _ecarts(chemin) if "ci.yml" in e]

    assert ecarts, "un workflow citant un autre tag doit échouer"
    assert "au lieu de" in ecarts[0]
    assert "autre combinaison" in ecarts[0]


def test_workflow_in_sync_is_silent(depot):
    chemin = depot(core_tag="bim-core-v0.3.0", workflow_core_tag="bim-core-v0.3.0")
    assert not [e for e in _ecarts(chemin) if "ci.yml" in e]


# ── dérive 3 : lock absent ou désaccordé ───────────────────────────────


def test_package_missing_from_lock_is_caught(depot, tmp_path):
    chemin = depot()
    (tmp_path / "uv.lock").write_text("", encoding="utf-8")
    ecarts = [e for e in _ecarts(chemin) if "absent de uv.lock" in e]

    assert len(ecarts) == 2, ecarts  # les deux paquets déclarés


def test_missing_lock_file_is_tolerated(depot):
    """Sans lock du tout, on ne prétend pas vérifier ce qu'il contient."""
    chemin = depot(avec_lock=False)
    assert not [e for e in _ecarts(chemin) if "uv.lock" in e]


# ── dérive 4 : installé ≠ épinglé ──────────────────────────────────────


def test_installed_version_mismatch_is_caught(depot):
    """Le contrôle porte sur l'ENVIRONNEMENT, pas sur les fichiers.

    ``bim-core`` est réellement installé ici ; la fixture épingle une version
    différente, ce qui doit être signalé.
    """
    import importlib.metadata

    installee = importlib.metadata.version("bim-core")
    autre = "9.9.9" if installee != "9.9.9" else "8.8.8"
    chemin = depot(core_spec=">=0.1.0,<10", core_tag=f"bim-core-v{autre}")

    ecarts = [e for e in _ecarts(chemin) if "INSTALLÉE" in e]
    assert ecarts, "une version installée différente du tag doit être signalée"
    assert "un pin correct ne dit rien" in ecarts[0]


def test_absent_optional_package_is_refused_in_strict_mode(depot, monkeypatch):
    """Un paquet **optionnel absent** doit échouer en mode strict.

    C'est l'angle mort du garde-fou : hors mode strict, une brique non installée
    est simplement ignorée — et « ignoré » ressemble à « conforme » dans un
    rapport vert. Or c'est exactement le cas d'``ifc-geometry-mcp``, installé
    par le seul extra ``geometry`` : un job qui ne l'installe pas ne prouve rien
    sur sa version.

    ``installed_version`` est substitué pour rendre le test déterministe, quel
    que soit l'environnement où il tourne.
    """
    import check_first_party_pins as guard

    monkeypatch.setattr(
        guard,
        "installed_version",
        lambda nom: None if nom == "ifc-geometry-mcp" else "0.3.0",
    )
    chemin = depot(core_tag="bim-core-v0.3.0", geo_tag="ifc-geometry-mcp-v0.3.0")

    souple = guard.check(Path(chemin), strict_installed=False)
    strict = guard.check(Path(chemin), strict_installed=True)

    assert not any("ifc-geometry-mcp" in e for e in souple), (
        "hors mode strict, une brique absente est tolérée"
    )
    manquants = [e for e in strict if "ifc-geometry-mcp" in e and "non installé" in e]
    assert manquants, "en mode strict, une brique absente doit être refusée"


def test_strict_mode_is_silent_when_everything_is_installed(depot, monkeypatch):
    """Le mode strict n'invente pas d'écart quand tout concorde."""
    import check_first_party_pins as guard

    monkeypatch.setattr(guard, "installed_version", lambda _nom: "0.3.0")
    chemin = depot(core_tag="bim-core-v0.3.0", geo_tag="ifc-geometry-mcp-v0.3.0")

    assert guard.check(Path(chemin), strict_installed=True) == []


def test_ci_installs_the_geometry_backend_for_the_strict_check():
    """Garde-fou du garde-fou : la CI doit installer ``ifc-geometry-mcp``.

    Sans cette installation, le contrôle d'environnement passe en ignorant
    précisément le paquet dont l'incident est parti. Ce test relie le script à
    son usage réel en CI — les deux étaient corrects séparément et inopérants
    ensemble.
    """
    ci = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    strictes = [ligne for ligne in ci.splitlines() if "--strict-installed" in ligne]
    assert strictes, "aucun appel en mode strict dans la CI"
    assert "ifc-geometry-mcp.git@ifc-geometry-mcp-v" in ci, (
        "le job strict doit installer ifc-geometry-mcp depuis son tag"
    )


# ── briques du script ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("tag", "attendu"),
    [
        ("bim-core-v0.3.0", "0.3.0"),
        ("ifc-geometry-mcp-v0.2.1", "0.2.1"),
        ("bim-core", None),
        ("legacy-i3f-mcp-v1.0", "1.0"),
    ],
)
def test_tag_version_extraction(tag, attendu):
    assert tag_version(tag) == attendu


@pytest.mark.parametrize(
    ("version", "spec", "attendu"),
    [
        ("0.3.0", ">=0.3.0,<0.4", True),
        ("0.2.0", ">=0.3.0,<0.4", False),
        ("0.4.0", ">=0.3.0,<0.4", False),
        ("0.3.1", ">=0.3.0,<0.4", True),
        ("1.0", ">=1,<2", True),
        ("0.1.1", ">=0.1.0,<0.2", True),
    ],
)
def test_version_satisfaction(version, spec, attendu):
    assert satisfies(version, spec) is attendu


def test_unknown_operator_is_reported_not_ignored():
    """Un contrôle qui laisse passer ce qu'il ne comprend pas ne protège de rien."""
    with pytest.raises(ValueError, match="non géré"):
        satisfies("0.3.0", "~=0.3.0")


# ── le dépôt réel doit rester cohérent ─────────────────────────────────


def test_this_repository_is_coherent():
    """Le garde-fou tourne aussi sur le vrai dépôt — c'est son objet."""
    racine = Path(__file__).resolve().parents[2]
    assert check(racine) == []
