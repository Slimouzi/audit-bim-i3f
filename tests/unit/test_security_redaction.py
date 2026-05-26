"""Tests du module ``audit_bim.security.redaction``."""

from __future__ import annotations

from audit_bim.security.redaction import redact_secrets


class TestBearerRedaction:
    def test_bearer_token_scrubbed(self):
        out = redact_secrets("Authorization: Bearer abcd12345678efgh")
        assert "abcd12345678efgh" not in out
        assert "<scrub:" in out
        assert "Bearer" in out

    def test_token_keyword_also_handled(self):
        out = redact_secrets("Authorization: Token abcd12345678efgh")
        assert "abcd12345678efgh" not in out
        assert "<scrub:" in out

    def test_short_token_left_alone(self):
        # < 8 chars : probable identifiant non-sensible
        out = redact_secrets("Bearer abc")
        assert "abc" in out
        assert "<scrub:" not in out


class TestKvRedaction:
    def test_access_token_equals(self):
        out = redact_secrets("GET /url?access_token=abcd12345678efgh&page=1")
        assert "abcd12345678efgh" not in out
        assert "access_token=<scrub:" in out
        # Le param suivant ne doit pas être scrubé
        assert "page=1" in out

    def test_access_token_colon(self):
        out = redact_secrets("access_token: abcd12345678efgh")
        assert "abcd12345678efgh" not in out
        assert "access_token:<scrub:" in out

    def test_authorization_header(self):
        out = redact_secrets("Authorization=abcd12345678efgh")
        assert "abcd12345678efgh" not in out
        assert "<scrub:" in out

    def test_api_key_variants(self):
        for key in ("api_key", "apikey", "API_KEY"):
            out = redact_secrets(f"{key}=abcd12345678efgh")
            assert "abcd12345678efgh" not in out

    def test_bimdata_api_key(self):
        out = redact_secrets("BIMDATA_API_KEY=abcd12345678efgh-xyz")
        assert "abcd12345678efgh-xyz" not in out

    def test_client_secret(self):
        out = redact_secrets("client_secret=abcd12345678efgh")
        assert "abcd12345678efgh" not in out

    def test_password(self):
        out = redact_secrets("password=abcd12345678efgh")
        assert "abcd12345678efgh" not in out

    def test_case_insensitive(self):
        out = redact_secrets("AcCeSs_ToKeN=abcd12345678efgh")
        assert "abcd12345678efgh" not in out


class TestRecursiveRedaction:
    def test_dict_scrubbed(self):
        out = redact_secrets({"err": "401 Bearer abcd12345678efgh"})
        assert "abcd12345678efgh" not in out["err"]

    def test_nested_dict(self):
        out = redact_secrets({"a": {"b": {"err": "access_token=abcd12345678efgh"}}})
        assert "abcd12345678efgh" not in out["a"]["b"]["err"]

    def test_list_scrubbed(self):
        out = redact_secrets(["Bearer abcd12345678efgh", "ok"])
        assert "abcd12345678efgh" not in out[0]
        assert out[1] == "ok"

    def test_tuple_scrubbed(self):
        out = redact_secrets(("Bearer abcd12345678efgh",))
        assert "abcd12345678efgh" not in out[0]
        assert isinstance(out, tuple)

    def test_non_string_types_passthrough(self):
        assert redact_secrets(42) == 42
        assert redact_secrets(None) is None
        assert redact_secrets(3.14) == 3.14
        assert redact_secrets(True) is True


class TestRealisticHttpErrors:
    def test_requests_exception_with_url(self):
        msg = (
            "HTTPError: 401 Unauthorized for url: "
            "https://api.example.com/cloud?access_token=eyJabcd12345678efgh"
        )
        out = redact_secrets(msg)
        assert "eyJabcd12345678efgh" not in out
        assert "access_token=<scrub:" in out
        # Le code HTTP et le path de l'URL doivent rester lisibles pour
        # le debug (on vérifie le path /cloud? plutôt que le host, pour
        # éviter un faux positif CodeQL py/incomplete-url-substring-sanitization
        # — ce test n'a pas pour but de valider l'origine d'une URL).
        assert "/cloud?" in out
        assert "HTTPError: 401" in out

    def test_curl_like_header(self):
        msg = "curl: (60) -H 'Authorization: Bearer eyJabcd12345678'"
        out = redact_secrets(msg)
        assert "eyJabcd12345678" not in out

    def test_empty_string(self):
        assert redact_secrets("") == ""

    def test_no_secrets(self):
        msg = "HTTPError: 404 Not Found"
        assert redact_secrets(msg) == msg
