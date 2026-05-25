"""Tests du module ``audit_bim.enrichment``.

Tous les appels HTTP sont mockés — aucun test ne sort sur le réseau.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from audit_bim.enrichment import (
    DPERecord,
    EnrichmentReport,
    GeocodingResult,
    GeoriskReport,
    PLUZoning,
    ProjectAddress,
    enrich_with_public_data,
    geocode_address,
    lookup_dpe,
    lookup_georisques,
    lookup_plu,
    resolve_project_address,
)

# ── Helpers ─────────────────────────────────────────────────────────────


class _FakeResp:
    """Mini-stub de ``requests.Response`` pour patcher requests.get."""

    def __init__(self, payload: dict, status: int = 200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _snapshot(buildings=None, sites=None) -> SimpleNamespace:
    """ModelSnapshot minimal (canard) avec ``buildings`` et ``sites``."""
    return SimpleNamespace(buildings=buildings or [], sites=sites or [])


def _ban_feature(
    *,
    label="10 Rue de Rivoli 75004 Paris",
    citycode="75104",
    postcode="75004",
    score=0.97,
    lon=2.355,
    lat=48.855,
    type_="housenumber",
) -> dict:
    return {
        "features": [
            {
                "properties": {
                    "label": label,
                    "citycode": citycode,
                    "postcode": postcode,
                    "score": score,
                    "type": type_,
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        ]
    }


# ── ProjectAddress / resolve_project_address ────────────────────────────


class TestResolveAddress:
    def test_override_wins(self):
        snap = _snapshot(buildings=[{"BuildingAddress": {"Town": "Lyon"}}])
        addr = resolve_project_address(snap, override="1 rue X, 75001 Paris")
        assert addr.source == "override"
        assert addr.address_lines == ["1 rue X, 75001 Paris"]

    def test_override_source_doe_tagged(self):
        addr = resolve_project_address(_snapshot(), override="addr", override_source="doe")
        assert addr.source == "doe"

    def test_override_source_unknown_falls_back(self):
        addr = resolve_project_address(_snapshot(), override="addr", override_source="bogus")
        assert addr.source == "override"

    def test_extract_from_building(self):
        snap = _snapshot(
            buildings=[
                {
                    "BuildingAddress": {
                        "AddressLines": ["10 Rue de Rivoli"],
                        "PostalCode": "75004",
                        "Town": "Paris",
                        "Country": "France",
                    }
                }
            ]
        )
        addr = resolve_project_address(snap)
        assert addr.source == "ifc_building"
        assert addr.postal_code == "75004"
        assert addr.town == "Paris"
        assert addr.address_lines == ["10 Rue de Rivoli"]

    def test_fallback_to_site_when_building_empty(self):
        snap = _snapshot(
            buildings=[{"BuildingAddress": None}],
            sites=[{"SiteAddress": {"Town": "Marseille", "PostalCode": "13001"}}],
        )
        addr = resolve_project_address(snap)
        assert addr.source == "ifc_site"
        assert addr.town == "Marseille"

    def test_address_lines_string_normalized_to_list(self):
        snap = _snapshot(
            buildings=[{"BuildingAddress": {"AddressLines": "5 Av des Champs", "Town": "Paris"}}]
        )
        addr = resolve_project_address(snap)
        assert addr.address_lines == ["5 Av des Champs"]

    def test_raises_when_nothing_found(self):
        with pytest.raises(ValueError, match="Aucune adresse"):
            resolve_project_address(_snapshot())

    def test_to_query_concatenates(self):
        addr = ProjectAddress(address_lines=["10 Rue de Rivoli"], postal_code="75004", town="Paris")
        assert addr.to_query() == "10 Rue de Rivoli 75004 Paris"


# ── BAN ──────────────────────────────────────────────────────────────────


class TestGeocodeAddress:
    def test_returns_match_with_score_and_coords(self):
        addr = ProjectAddress(address_lines=["10 Rue de Rivoli"], town="Paris")
        with patch("audit_bim.enrichment.ban.requests.get") as g:
            g.return_value = _FakeResp(_ban_feature())
            res = geocode_address(addr)
        assert res.matched is True
        assert res.score == pytest.approx(0.97)
        assert res.citycode == "75104"
        assert res.lon == 2.355
        assert res.lat == 48.855

    def test_empty_query_short_circuits(self):
        addr = ProjectAddress()
        # Pas de HTTP call attendu
        with patch("audit_bim.enrichment.ban.requests.get") as g:
            res = geocode_address(addr)
            g.assert_not_called()
        assert res.matched is False

    def test_no_features_returns_unmatched(self):
        addr = ProjectAddress(address_lines=["zzz"], town="zzz")
        with patch("audit_bim.enrichment.ban.requests.get") as g:
            g.return_value = _FakeResp({"features": []})
            res = geocode_address(addr)
        assert res.matched is False

    def test_http_error_returns_unmatched_with_error(self):
        addr = ProjectAddress(address_lines=["x"], town="y")
        with patch("audit_bim.enrichment.ban.requests.get") as g:
            g.side_effect = requests.ConnectionError("boom")
            res = geocode_address(addr)
        assert res.matched is False
        assert "boom" in (res.raw or {}).get("error", "")


# ── DPE ──────────────────────────────────────────────────────────────────


class TestLookupDpe:
    def test_returns_empty_if_geo_unmatched(self):
        geo = GeocodingResult(matched=False)
        assert lookup_dpe(geo) == []

    def test_returns_empty_if_no_coords(self):
        geo = GeocodingResult(matched=True, lat=None, lon=None)
        assert lookup_dpe(geo) == []

    def test_parses_records(self):
        geo = GeocodingResult(matched=True, lat=48.855, lon=2.355)
        payload = {
            "results": [
                {
                    "n_dpe": "ABC123",
                    "date_etablissement_dpe": "2023-04-15",
                    "etiquette_dpe": "C",
                    "etiquette_ges": "B",
                    "conso_5_usages_par_m2_ep": "180.5",
                    "emission_ges_5_usages_par_m2": "22.1",
                    "type_batiment": "appartement",
                    "annee_construction": "1970",
                    "surface_habitable_logement": "65.2",
                    "adresse_brut": "10 Rue de Rivoli, 75004 Paris",
                }
            ]
        }
        with patch("audit_bim.enrichment.dpe.requests.get") as g:
            g.return_value = _FakeResp(payload)
            records = lookup_dpe(geo)
        assert len(records) == 1
        r = records[0]
        assert isinstance(r, DPERecord)
        assert r.etiquette_dpe == "C"
        assert r.annee_construction == 1970
        assert r.consommation_kwh_m2_an == pytest.approx(180.5)

    def test_http_error_returns_empty(self):
        geo = GeocodingResult(matched=True, lat=48.855, lon=2.355)
        with patch("audit_bim.enrichment.dpe.requests.get") as g:
            g.side_effect = requests.Timeout("timeout")
            assert lookup_dpe(geo) == []

    def test_handles_missing_fields_gracefully(self):
        geo = GeocodingResult(matched=True, lat=48.855, lon=2.355)
        with patch("audit_bim.enrichment.dpe.requests.get") as g:
            g.return_value = _FakeResp({"results": [{}]})
            records = lookup_dpe(geo)
        assert len(records) == 1
        assert records[0].etiquette_dpe is None
        assert records[0].annee_construction is None


# ── PLU ──────────────────────────────────────────────────────────────────


class TestLookupPlu:
    def test_returns_empty_if_geo_unmatched(self):
        assert lookup_plu(GeocodingResult(matched=False)) == []

    def test_parses_zones(self):
        geo = GeocodingResult(matched=True, lat=48.855, lon=2.355)
        payload = {
            "features": [
                {
                    "properties": {
                        "typezone": "U",
                        "libelle": "UAa1",
                        "nomfic": "75056_PLU_2023.pdf",
                        "nom_commune": "Paris",
                    }
                },
                {
                    "properties": {
                        "typezone": "N",
                        "libelong": "Zone naturelle",
                        "commune": "Paris",
                    }
                },
            ]
        }
        with patch("audit_bim.enrichment.plu.requests.get") as g:
            g.return_value = _FakeResp(payload)
            zones = lookup_plu(geo)
        assert len(zones) == 2
        assert isinstance(zones[0], PLUZoning)
        assert zones[0].libelle == "UAa1"
        assert zones[1].libelle == "Zone naturelle"  # fallback libelong

    def test_http_error_returns_empty(self):
        geo = GeocodingResult(matched=True, lat=48.855, lon=2.355)
        with patch("audit_bim.enrichment.plu.requests.get") as g:
            g.side_effect = requests.ConnectionError("nope")
            assert lookup_plu(geo) == []


# ── Géorisques ───────────────────────────────────────────────────────────


class TestLookupGeorisques:
    def test_returns_empty_if_no_citycode(self):
        geo = GeocodingResult(matched=True, lat=1.0, lon=2.0, citycode=None)
        report = lookup_georisques(geo)
        assert isinstance(report, GeoriskReport)
        assert report.nb_aleas == 0

    def test_aggregates_items_across_endpoints(self):
        geo = GeocodingResult(matched=True, lat=48.855, lon=2.355, citycode="75104")

        def fake_get(url, params=None, timeout=None):
            if "gaspar" in url:
                return _FakeResp({"data": [{"libelle_risque_long": "Inondation"}]})
            if "installations_classees" in url:
                return _FakeResp(
                    {"results": [{"nom_etablissement": "Usine X", "regime": "Seveso"}]}
                )
            if "mvt" in url:
                return _FakeResp({"data": []})
            return _FakeResp({}, status=404)

        with patch("audit_bim.enrichment.georisques.requests.get", side_effect=fake_get):
            report = lookup_georisques(geo)
        assert report.nb_aleas == 2
        types = {it.type for it in report.items}
        assert "risque_naturel" in types
        assert "icpe" in types

    def test_endpoint_404_ignored(self):
        geo = GeocodingResult(matched=True, lat=48.855, lon=2.355, citycode="75104")

        def fake_get(url, params=None, timeout=None):
            return _FakeResp({}, status=404)

        with patch("audit_bim.enrichment.georisques.requests.get", side_effect=fake_get):
            report = lookup_georisques(geo)
        assert report.nb_aleas == 0


# ── Orchestrator ─────────────────────────────────────────────────────────


class TestEnrichWithPublicData:
    def test_stops_at_ban_if_unmatched(self):
        snap = _snapshot(buildings=[{"BuildingAddress": {"AddressLines": ["x"], "Town": "y"}}])
        with patch("audit_bim.enrichment.ban.requests.get") as g:
            g.return_value = _FakeResp({"features": []})
            report = enrich_with_public_data(snap)
        assert isinstance(report, EnrichmentReport)
        assert report.geocoding.matched is False
        assert report.sources_used == []
        assert report.dpe_records == []

    def test_full_pipeline_with_all_sources(self):
        snap = _snapshot(
            buildings=[
                {
                    "BuildingAddress": {
                        "AddressLines": ["10 Rue de Rivoli"],
                        "PostalCode": "75004",
                        "Town": "Paris",
                    }
                }
            ]
        )

        def fake_get(url, params=None, timeout=None):
            if "api-adresse" in url:
                return _FakeResp(_ban_feature())
            if "ademe" in url:
                return _FakeResp({"results": [{"etiquette_dpe": "D"}]})
            if "apicarto" in url:
                return _FakeResp({"features": [{"properties": {"typezone": "U", "libelle": "UA"}}]})
            if "georisques" in url:
                return _FakeResp({"data": [{"libelle_risque_long": "Inondation"}]})
            return _FakeResp({}, status=404)

        with (
            patch("audit_bim.enrichment.ban.requests.get", side_effect=fake_get),
            patch("audit_bim.enrichment.dpe.requests.get", side_effect=fake_get),
            patch("audit_bim.enrichment.plu.requests.get", side_effect=fake_get),
            patch("audit_bim.enrichment.georisques.requests.get", side_effect=fake_get),
        ):
            report = enrich_with_public_data(snap)

        assert report.geocoding.matched is True
        assert "ban" in report.sources_used
        assert "dpe-ademe" in report.sources_used
        assert "plu-gpu" in report.sources_used
        assert "georisques" in report.sources_used
        assert report.dpe_records and report.dpe_records[0].etiquette_dpe == "D"
        assert report.plu_zones and report.plu_zones[0].typezone == "U"
        assert report.georisks.nb_aleas >= 1

    def test_can_disable_sources(self):
        snap = _snapshot(
            buildings=[
                {
                    "BuildingAddress": {
                        "AddressLines": ["10 Rue de Rivoli"],
                        "Town": "Paris",
                    }
                }
            ]
        )

        # ``requests`` est partagé entre les sous-modules : un seul patch
        # central qui dispatche par URL suffit (et c'est plus fidèle à la
        # réalité d'un appel HTTP que 4 patches superposés).
        calls: list[str] = []

        def fake_get(url, params=None, timeout=None):
            calls.append(url)
            if "api-adresse" in url:
                return _FakeResp(_ban_feature())
            raise AssertionError(f"URL inattendue : {url}")

        with patch("audit_bim.enrichment.ban.requests.get", side_effect=fake_get):
            report = enrich_with_public_data(
                snap, include_dpe=False, include_plu=False, include_georisques=False
            )

        assert report.sources_used == ["ban"]
        assert all("api-adresse" in u for u in calls)

    def test_source_error_does_not_break_pipeline(self):
        snap = _snapshot(buildings=[{"BuildingAddress": {"AddressLines": ["x"], "Town": "Paris"}}])

        def fake_get(url, params=None, timeout=None):
            if "api-adresse" in url:
                return _FakeResp(_ban_feature())
            if "ademe" in url:
                raise requests.ConnectionError("dpe down")
            if "apicarto" in url:
                return _FakeResp({"features": []})
            if "georisques" in url:
                return _FakeResp({"data": []})
            return _FakeResp({}, status=404)

        with patch("audit_bim.enrichment.ban.requests.get", side_effect=fake_get):
            report = enrich_with_public_data(snap)

        # DPE renvoie [] (l'erreur est avalée par lookup_dpe lui-même),
        # le pipeline continue sur PLU + Géorisques.
        assert "ban" in report.sources_used
        assert "plu-gpu" in report.sources_used
        assert "georisques" in report.sources_used
        assert report.dpe_records == []

    def test_doe_override_tagged_in_report(self):
        snap = _snapshot()
        with patch("audit_bim.enrichment.ban.requests.get") as g:
            g.return_value = _FakeResp({"features": []})
            report = enrich_with_public_data(
                snap,
                address_override="42 avenue X 75001 Paris",
                address_override_source="doe",
                include_dpe=False,
                include_plu=False,
                include_georisques=False,
            )
        assert report.address.source == "doe"
        assert report.address.address_lines == ["42 avenue X 75001 Paris"]
