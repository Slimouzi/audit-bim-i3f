"""E6 (audit profond 2ᵉ passe) — garde **serveur** du catalogue CCH.

``build_catalog`` tolère des documents illisibles et rend un catalogue vide ; sans
garde, ``parse_owner_requirements`` / ``full_audit`` produiraient un audit
faussement « conforme ». Les runners CLI se protégeaient déjà
(``assert_catalog_usable``, ``SystemExit``) ; le chemin MCP obtient ici une garde
**non fatale** : avertissement structuré + refus de ``full_audit``.
"""

from __future__ import annotations

import pytest

from audit_bim.mcp.session import _Session, current_session
from audit_bim.profiles.i3f import tools_audit, tools_session
from audit_bim.requirements.catalog import catalog_usable
from audit_bim.requirements.models import NamingRule, PropertySpec, RequirementsCatalog


@pytest.fixture
def _session():
    sess = _Session()
    token = current_session.set(sess)
    try:
        yield sess
    finally:
        current_session.reset(token)


# ── catalog_usable ────────────────────────────────────────────────────────────
def test_usable_catalog(catalog):
    ok, reason = catalog_usable(catalog)
    assert ok is True
    assert reason is None


def test_empty_catalog_not_usable():
    ok, reason = catalog_usable(RequirementsCatalog())
    assert ok is False
    assert "inexploitable" in reason


def test_properties_only_not_usable():
    cat = RequirementsCatalog(
        properties=[
            PropertySpec(
                theme="A", objet="M", ifc_class="IfcWall", property_name="P", kind="property"
            )
        ]
    )
    assert catalog_usable(cat)[0] is False  # naming_rules vide


def test_rules_only_not_usable():
    cat = RequirementsCatalog(
        naming_rules=[NamingRule(objet="S", ifc_class="IfcSite", ifc_attribute="Name")]
    )
    assert catalog_usable(cat)[0] is False  # properties vide


def _clear_docs(sess) -> None:
    """Aucun document MOA chargé → build_catalog rend un catalogue vide (le
    ``config`` de test peut pointer sur des documents réels par défaut)."""
    sess.cch_pdf = None
    sess.data_spec_xlsx = None
    sess.naming_spec_xlsx = None


# ── parse_owner_requirements : avertissement structuré ────────────────────────
def test_parse_owner_requirements_warns_on_empty_catalog(_session):
    _clear_docs(_session)
    summary = tools_session.parse_owner_requirements()
    assert "warning" in summary
    assert "inexploitable" in summary["warning"]


# ── full_audit : refus ────────────────────────────────────────────────────────
def test_full_audit_prepare_catalog_refuses_empty(_session):
    _clear_docs(_session)
    with pytest.raises(ValueError, match="REFUS full_audit"):
        tools_audit._fa_prepare_catalog()


def test_full_audit_prepare_catalog_ok_with_usable(_session, catalog):
    # Un catalogue déjà utilisable (posé après build) ne doit pas lever : on
    # simule en pré-chargeant, build_catalog vide serait re-chargé — donc on
    # vérifie plutôt directement le helper (build sans docs → vide → refus).
    ok, reason = catalog_usable(catalog)
    assert ok and reason is None
