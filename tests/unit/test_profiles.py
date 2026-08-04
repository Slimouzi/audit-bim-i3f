from __future__ import annotations

from pathlib import Path

import pytest

from audit_bim.profiles import (
    DEFAULT_PROFILE_ID,
    get_profile,
    list_generic_modules,
    list_profiles,
    profiles_payload,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_i3f_is_default_profile_and_keeps_avp_pack():
    profile = get_profile(DEFAULT_PROFILE_ID)
    assert profile.id == "i3f"
    assert profile.is_default is True
    assert "avp_i3f" in profile.report_packs
    assert profile.default_catalog_label == "CCH BIM I3F V3.x"


def test_bim_in_motion_profile_is_available_without_i3f_pack():
    profile = get_profile("bim-in-motion")
    assert profile.id == "bim_in_motion"
    assert profile.owner_name == "BIM in Motion"
    assert "avp_i3f" not in profile.report_packs

    # Depuis E5, le prompt et les outils du profil existent réellement ; le
    # référentiel et les packs restent à faire. Un « tout planned » décrirait
    # un profil vide, ce que le registre ne doit plus prétendre.
    ready = {s.key for s in profile.specializations if s.status == "ready"}
    assert ready == {"prompt_bim_in_motion", "tools_bim_in_motion"}
    assert any(s.status == "planned" for s in profile.specializations)


def test_profiles_compose_the_same_generic_module_keys():
    module_keys = {m.key for m in list_generic_modules()}
    assert {"extraction", "geometry", "bcf", "classifier", "doe", "enrichment"} <= module_keys
    for profile in list_profiles():
        assert set(profile.enabled_generic_modules) == module_keys


def test_profile_ids_are_unique_and_unknown_ids_fail():
    ids = [p.id for p in list_profiles()]
    assert len(ids) == len(set(ids))
    with pytest.raises(KeyError):
        get_profile("unknown")


def test_payload_is_json_friendly_and_filterable():
    out = profiles_payload("bim_in_motion")
    assert out["status"] == "ok"
    assert out["default_profile_id"] == "i3f"
    assert out["profile_id"] == "bim_in_motion"
    assert len(out["profiles"]) == 1
    assert isinstance(out["generic_modules"], list)
    assert isinstance(out["profiles"][0]["enabled_generic_modules"], list)


def test_ready_specializations_point_to_existing_paths():
    """Une spécialisation `ready` doit désigner du code qui existe encore.

    Le registre est purement déclaratif : rien ne le relie au disque. Le jour où
    `audit_bim/reporting/avp` partira vers un pack enfant — étape 1 de l'ordre
    d'extraction — ce test échoue au lieu de laisser la carte mentir en silence.
    """
    stale: list[str] = []
    for profile in list_profiles():
        for spec in profile.specializations:
            if spec.status != "ready" or spec.current_location is None:
                continue
            if not spec.current_location.startswith("audit_bim"):
                continue
            if not (_REPO_ROOT / spec.current_location).exists():
                stale.append(f"{profile.id}/{spec.key} -> {spec.current_location}")
    assert not stale, f"current_location introuvable(s) sur disque : {stale}"
