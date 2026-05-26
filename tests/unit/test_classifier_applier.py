"""Tests ciblés de :func:`audit_bim.classifier.applier.apply_classifications`.

Couvre en particulier le contrat ``linked_uuids`` / ``failed_uuids``
ajouté pour la review CTO P2 (statuts APPLIED partiels).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from audit_bim.classifier.applier import apply_classifications


def _mock_client(*, list_existing=None, post_classification=None, post_link=None):
    """Construit un client BIMData mock.

    Args:
        list_existing: Liste de classifs existantes (pour
            ``list_project_classifications``).
        post_classification: Side effect pour la création de classif.
            Si callable, appelé avec ``(url, data)``. Si dict, retourné
            tel quel. Si Exception, levée.
        post_link: Side effect pour le bulk-link. Idem.
    """
    client = MagicMock()
    client.cloud_id = "1"
    client.project_id = "2"
    client.model_id = "3"

    list_existing = list_existing or []

    def _get(url):
        if "/classification" in url and "-element" not in url:
            return list_existing
        return []

    client._get.side_effect = _get

    def _post(url, body):
        if "/classification-element" in url:
            if isinstance(post_link, Exception):
                raise post_link
            if callable(post_link):
                return post_link(url, body)
            return post_link or {}
        # création classif
        if isinstance(post_classification, Exception):
            raise post_classification
        if callable(post_classification):
            return post_classification(url, body)
        return post_classification or {"id": 100}

    client._post.side_effect = _post
    return client


class TestApplyClassificationsLinkedUuids:
    def test_all_linked_when_no_error(self):
        client = _mock_client(post_classification={"id": 100})
        items = [
            {"uuid": "W1", "code": "B2010", "system": "uniformat"},
            {"uuid": "W2", "code": "C1010", "system": "uniformat"},
        ]
        # Chaque POST de classif renvoie un id incrémenté.
        ids = iter([100, 101])
        client._post.side_effect = lambda url, body: (
            {} if "/classification-element" in url else {"id": next(ids)}
        )

        res = apply_classifications(client, items, dry_run=False)
        assert res["link_failed"] is False
        assert sorted(res["linked_uuids"]) == ["W1", "W2"]
        assert res["failed_uuids"] == []
        assert res["n_links_created"] == 2

    def test_link_failure_moves_all_to_failed(self):
        client = _mock_client(
            post_classification={"id": 100},
            post_link=RuntimeError("bulk link 500"),
        )
        ids = iter([100, 101])

        def _post(url, body):
            if "/classification-element" in url:
                raise RuntimeError("bulk link 500")
            return {"id": next(ids)}

        client._post.side_effect = _post

        items = [
            {"uuid": "W1", "code": "B2010", "system": "uniformat"},
            {"uuid": "W2", "code": "C1010", "system": "uniformat"},
        ]
        res = apply_classifications(client, items, dry_run=False)
        assert res["link_failed"] is True
        assert res["linked_uuids"] == []
        assert sorted(res["failed_uuids"]) == ["W1", "W2"]

    def test_creation_failure_partial(self):
        """Création OK pour C1010 mais KO pour B2010 → W1 lié, W2 perdu."""
        items = [
            {"uuid": "W1", "code": "C1010", "system": "uniformat"},
            {"uuid": "W2", "code": "B2010", "system": "uniformat"},
        ]
        creation_calls = []

        def _post(url, body):
            if "/classification-element" in url:
                # bulk link OK pour ce qui a survécu à la création.
                return {}
            creation_calls.append(body)
            if (body.get("notation") or "").upper() == "B2010":
                raise RuntimeError("create B2010 failed: 422")
            return {"id": 200 + len(creation_calls)}

        client = _mock_client()
        client._post.side_effect = _post

        res = apply_classifications(client, items, dry_run=False)
        # Seul W1 a été lié (sa classif C1010 a été créée avec succès)
        assert res["linked_uuids"] == ["W1"]
        assert res["failed_uuids"] == ["W2"]
        assert res["link_failed"] is False
        assert res["n_links_created"] == 1
        assert any("B2010" in e for e in res["errors"])

    def test_dry_run_does_not_expose_linked_uuids(self):
        client = _mock_client()
        items = [{"uuid": "W1", "code": "B2010", "system": "uniformat"}]
        res = apply_classifications(client, items, dry_run=True)
        # En dry_run on garde le contrat historique (pas de
        # linked_uuids / failed_uuids — pas d'exécution réelle).
        assert "linked_uuids" not in res
        assert "failed_uuids" not in res
        assert res["dry_run"] is True
