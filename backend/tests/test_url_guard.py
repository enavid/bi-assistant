"""Tests for the outbound URL/host SSRF guard — TDD.

Covers the Ollama HTTP allow-list path and the database-host block-list path,
including the adversarial cases (cloud-metadata IP, link-local, scheme abuse).
"""

from __future__ import annotations

import pytest

from app.core.url_guard import (
    OutboundURLNotAllowed,
    validate_db_host,
    validate_http_url,
)

_ALLOWLIST = ["localhost", "127.0.0.1", "::1"]


# ---------------------------------------------------------------------------
# validate_http_url — Ollama outbound (deny-by-default allow-list)
# ---------------------------------------------------------------------------


def test_http_url_allows_localhost_in_allowlist():
    url = "http://localhost:11434"
    assert validate_http_url(url, allowlist=_ALLOWLIST) == url


def test_http_url_allows_loopback_ip_in_allowlist():
    assert validate_http_url("http://127.0.0.1:11434/api/tags", allowlist=_ALLOWLIST)


def test_http_url_allows_https_scheme():
    assert validate_http_url("https://localhost", allowlist=_ALLOWLIST)


def test_http_url_is_case_insensitive_on_host():
    assert validate_http_url("http://LOCALHOST:11434", allowlist=_ALLOWLIST)


def test_http_url_trims_whitespace():
    assert validate_http_url("  http://localhost:11434  ", allowlist=_ALLOWLIST) == (
        "http://localhost:11434"
    )


def test_http_url_rejects_host_not_in_allowlist():
    with pytest.raises(OutboundURLNotAllowed):
        validate_http_url("http://evil.example.com:11434", allowlist=_ALLOWLIST)


def test_http_url_rejects_private_lan_host_not_in_allowlist():
    # An attacker pivoting to an internal service must be blocked unless explicitly allowed.
    with pytest.raises(OutboundURLNotAllowed):
        validate_http_url("http://10.0.0.5:8080", allowlist=_ALLOWLIST)


def test_http_url_rejects_cloud_metadata_even_if_allowlisted():
    # The cloud metadata endpoint must never be reachable, even by misconfiguration.
    with pytest.raises(OutboundURLNotAllowed):
        validate_http_url(
            "http://169.254.169.254/latest/meta-data/",
            allowlist=["169.254.169.254", *_ALLOWLIST],
        )


def test_http_url_rejects_ipv6_link_local():
    with pytest.raises(OutboundURLNotAllowed):
        validate_http_url("http://[fe80::1]:11434", allowlist=["fe80::1", *_ALLOWLIST])


def test_http_url_rejects_non_http_scheme():
    for bad in ("ftp://localhost", "file:///etc/passwd", "gopher://localhost:11434"):
        with pytest.raises(OutboundURLNotAllowed):
            validate_http_url(bad, allowlist=_ALLOWLIST)


def test_http_url_rejects_missing_scheme():
    with pytest.raises(OutboundURLNotAllowed):
        validate_http_url("localhost:11434", allowlist=_ALLOWLIST)


def test_http_url_rejects_empty():
    for bad in ("", "   ", None):
        with pytest.raises(OutboundURLNotAllowed):
            validate_http_url(bad, allowlist=_ALLOWLIST)  # type: ignore[arg-type]


def test_http_url_rejects_empty_allowlist():
    with pytest.raises(OutboundURLNotAllowed):
        validate_http_url("http://localhost:11434", allowlist=[])


# ---------------------------------------------------------------------------
# validate_db_host — database outbound (block-list of dangerous ranges)
# ---------------------------------------------------------------------------


def test_db_host_allows_regular_hostname():
    assert validate_db_host("db.company.com") == "db.company.com"


def test_db_host_allows_localhost_and_private_ip():
    # DB hosts are user-supplied by design; private/LAN targets are legitimate.
    assert validate_db_host("localhost") == "localhost"
    assert validate_db_host("10.1.2.3") == "10.1.2.3"
    assert validate_db_host("192.168.1.10") == "192.168.1.10"


def test_db_host_normalizes_case_and_whitespace():
    assert validate_db_host("  DB.Company.COM ") == "db.company.com"


def test_db_host_rejects_cloud_metadata():
    with pytest.raises(OutboundURLNotAllowed):
        validate_db_host("169.254.169.254")


def test_db_host_rejects_link_local_range():
    with pytest.raises(OutboundURLNotAllowed):
        validate_db_host("169.254.10.20")


def test_db_host_rejects_empty():
    for bad in ("", "   ", None):
        with pytest.raises(OutboundURLNotAllowed):
            validate_db_host(bad)  # type: ignore[arg-type]
