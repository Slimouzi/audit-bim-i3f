"""Les docs actives doivent nommer le serveur tel qu'il s'annonce.

Une consigne périmée en première page est une panne différée : un lecteur
configure ce qu'elle dit, et découvre l'écart plus tard, sans que rien ne le
lui signale. Le README affirmait encore « le nom du serveur MCP reste
`audit-bim-i3f` » alors que le serveur s'annonçait déjà autrement — une phrase
qui aurait été **fausse en première page**.

Le contrôle **dérive** le nom attendu de l'instance FastMCP elle-même. Il ne
recopie pas une chaîne : renommer le serveur sans mettre les docs à jour fait
donc échouer ce test, ce qui est exactement le service attendu.

Ce qu'il ne contrôle **pas**, délibérément : les chemins du dossier local
(non renommé), la distribution, les tags, et les récits historiques du
CHANGELOG. Ce sont d'autres lots, et les confondre produirait un balayage
aveugle au lieu d'un garde-fou.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Docs et snippets **actifs** : ce qu'un lecteur suit pour configurer.
#: Le CHANGELOG et les `docs/instruct-*` racontent le passé et sont exclus.
ACTIVE_DOCS = (
    REPO / "README.md",
    REPO / "SECURITY.md",
    REPO / "claude_desktop_config.example.json",
    REPO / "docs" / "claude_desktop_local.md",
    REPO / "docs" / "mcp_tools.md",
    *sorted((REPO / "examples").glob("*")),
)

CONFIG_EXAMPLE = REPO / "claude_desktop_config.example.json"


def _server_name() -> str:
    """Nom réellement annoncé par le serveur — lu, jamais recopié."""
    from audit_bim.mcp.app import mcp

    assert mcp.name, "prémisse : l'instance FastMCP doit porter un nom"
    return mcp.name


def test_the_server_name_is_readable():
    """Sentinelle : sans nom lisible, tous les contrôles seraient vacants."""
    assert _server_name() == "audit-bim-mcp"


@pytest.mark.parametrize("doc", ACTIVE_DOCS, ids=lambda p: str(p.relative_to(REPO)))
def test_no_active_doc_claims_another_server_name(doc):
    """Aucune doc active ne doit désigner le serveur par un autre nom.

    Le contrôle est ciblé : il cherche les tournures qui **nomment le serveur**
    (« serveur MCP X », « le MCP X », « nom du serveur MCP … X »), et non toute
    occurrence de la chaîne — un chemin ou une distribution portant l'ancien nom
    reste légitime.
    """
    if not doc.exists() or doc.is_dir():
        pytest.skip(f"{doc.name} absent")
    attendu = _server_name()
    texte = doc.read_text(encoding="utf-8")

    # Le token capturé doit être un NOM DE PRODUIT, sinon la recherche attrape
    # la prose ordinaire — « serveur MCP est configuré », « serveur MCP
    # multi-AMO ». Un garde-fou qui crie sur du français n'est pas resserré :
    # il est faux, et on finit par le désarmer.
    tournures = (
        r"serveur MCP\s+`?(audit-bim[\w.-]*)`?",
        r"\ble MCP\s+`(audit-bim[\w.-]*)`",
        r"nom du serveur MCP\s+\w*\s*`?(audit-bim[\w.-]*)`?",
    )
    offenders = [
        f"{match.group(0).strip()!r}"
        for motif in tournures
        for match in re.finditer(motif, texte)
        if match.group(1) != attendu
    ]
    assert not offenders, f"{doc.name} nomme un autre serveur que {attendu!r} : {offenders}"


@pytest.mark.parametrize("doc", ACTIVE_DOCS, ids=lambda p: str(p.relative_to(REPO)))
def test_no_active_snippet_uses_another_server_key(doc):
    """Les exemples de config doivent employer le nom courant comme clé.

    Une clé `mcpServers` est choisie par l'utilisateur, donc l'ancien nom n'y
    est pas *faux* techniquement — mais un exemple qui l'emploie enseigne un
    nom que le produit n'utilise plus.
    """
    if not doc.exists() or doc.is_dir():
        pytest.skip(f"{doc.name} absent")
    attendu = _server_name()
    texte = doc.read_text(encoding="utf-8")

    # Une clé de serveur, c'est un identifiant suivi d'un objet ou d'une
    # accolade — jamais un chemin, qui contient toujours un `/`.
    cles = re.findall(r'"([\w.-]+)"\s*:\s*\{', texte)
    offenders = [c for c in cles if c.startswith("audit-bim") and not c.startswith(attendu)]
    assert not offenders, f"{doc.name} déclare un serveur nommé {offenders} au lieu de {attendu!r}"


def test_the_config_example_declares_one_server_per_profile():
    """L'exemple doit enseigner la règle réelle : un processus = un profil.

    Le serveur ne bascule pas de profil à chaud. Un exemple à un seul serveur
    laisserait croire l'inverse à qui veut exposer plusieurs AMO.
    """
    charge = json.loads(CONFIG_EXAMPLE.read_text(encoding="utf-8"))
    serveurs = charge["mcpServers"]
    attendu = _server_name()

    assert all(nom.startswith(attendu) for nom in serveurs), list(serveurs)

    profils = {
        nom: (definition.get("env") or {}).get("AUDIT_BIM_PROFILE")
        for nom, definition in serveurs.items()
    }
    # Un serveur sans variable — le profil par défaut — et au moins un autre
    # qui la porte : c'est la démonstration que l'exemple doit faire.
    assert None in profils.values(), profils
    assert [p for p in profils.values() if p], profils


def test_the_key_guard_is_not_vacuous():
    """Le contrôle doit reconnaître la forme qu'il interdit, et elle seule."""
    interdit = '{"mcpServers": {"audit-bim-i3f": {"command": "python"}}}'
    cles = re.findall(r'"([\w.-]+)"\s*:\s*\{', interdit)
    assert [c for c in cles if c.startswith("audit-bim") and not c.startswith("audit-bim-mcp")]

    # Un chemin portant l'ancien nom ne doit PAS être vu comme une clé.
    chemin = '{"cwd": "/Users/stani/code/MCP/audit-bim-i3f"}'
    assert not [c for c in re.findall(r'"([\w.-]+)"\s*:\s*\{', chemin) if c.startswith("audit-bim")]


def test_the_name_guard_is_not_vacuous():
    """La recherche de tournures doit voir la phrase réellement corrigée."""
    ancien = "le nom du serveur MCP reste `audit-bim-i3f` : il figure partout."
    motif = r"serveur MCP\s+\w*\s*`?(audit-bim[\w.-]*)`?"
    trouve = [m.group(1) for m in re.finditer(motif, ancien) if m.group(1) != "audit-bim-mcp"]
    assert trouve == ["audit-bim-i3f"], trouve

    # Et la prose ordinaire ne doit rien déclencher, sinon le contrôle serait
    # désarmé au premier faux positif.
    for benin in (
        "Il héberge un serveur MCP multi-AMO : I3F en est le profil par défaut.",
        "Le serveur MCP est lancé depuis le venv.",
        "redémarrer le serveur MCP lui-même",
    ):
        assert not re.findall(motif, benin), benin
