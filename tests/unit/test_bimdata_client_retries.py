"""Politique de retry du :class:`BIMDataClient` — GET/HEAD seulement."""

from __future__ import annotations

from audit_bim.extraction.client import _build_retry_adapter


class TestRetryPolicy:
    def test_only_idempotent_methods(self):
        adapter = _build_retry_adapter()
        # urllib3.Retry expose les méthodes autorisées en frozenset
        retry = adapter.max_retries
        assert "GET" in retry.allowed_methods
        assert "HEAD" in retry.allowed_methods

    def test_post_not_retried(self):
        # Le fix review CTO round 2 retire POST des méthodes retried —
        # les POST BIMData créent (BCF, Smart View, classification),
        # un retry pourrait dupliquer.
        adapter = _build_retry_adapter()
        retry = adapter.max_retries
        assert "POST" not in retry.allowed_methods
        assert "PUT" not in retry.allowed_methods
        assert "DELETE" not in retry.allowed_methods

    def test_status_forcelist_429_5xx(self):
        adapter = _build_retry_adapter()
        retry = adapter.max_retries
        # Retries sur 429 (rate limit) + classe 5xx
        assert 429 in retry.status_forcelist
        assert 500 in retry.status_forcelist
        assert 502 in retry.status_forcelist
        assert 503 in retry.status_forcelist
        assert 504 in retry.status_forcelist

    def test_backoff_factor_set(self):
        adapter = _build_retry_adapter()
        retry = adapter.max_retries
        assert retry.backoff_factor > 0

    def test_respects_retry_after(self):
        adapter = _build_retry_adapter()
        retry = adapter.max_retries
        assert retry.respect_retry_after_header is True
