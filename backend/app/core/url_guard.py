"""Outbound URL/host guard to mitigate SSRF via user-supplied endpoints.

Two policies are provided:

* :func:`validate_http_url` — a deny-by-default allow-list for outbound HTTP(S)
  calls (used for the Ollama endpoints, whose ``base_url`` is user-controlled).
* :func:`validate_db_host` — a block-list of dangerous IP ranges for database
  hosts, which are user-supplied by design (admins connect to their own HR DB).

Both unconditionally reject cloud-metadata and link-local ranges so that a
misconfigured allow-list can never expose the instance metadata service.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from urllib.parse import urlparse

_ALLOWED_SCHEMES = ("http", "https")

# Ranges that must never be reachable, even if an operator allow-lists them.
# 169.254.0.0/16 covers the cloud metadata endpoint (169.254.169.254).
_HARD_BLOCKED_NETWORKS = (
    ipaddress.ip_network("169.254.0.0/16"),  # IPv4 link-local + cloud metadata
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
    ipaddress.ip_network("0.0.0.0/8"),  # "this network"
    ipaddress.ip_network("::/128"),  # unspecified
    ipaddress.ip_network("224.0.0.0/4"),  # IPv4 multicast
)


class OutboundURLNotAllowed(ValueError):
    """Raised when an outbound URL or host fails the SSRF policy checks."""


def _as_ip(host: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _is_hard_blocked(host: str) -> bool:
    ip = _as_ip(host)
    if ip is None:
        return False
    return any(ip in network for network in _HARD_BLOCKED_NETWORKS)


def validate_http_url(raw_url: str, *, allowlist: Sequence[str]) -> str:
    """Validate an outbound HTTP(S) URL against an allow-list of hosts.

    Returns the trimmed URL on success. Raises :class:`OutboundURLNotAllowed`
    when the scheme is not HTTP(S), the host is missing, the host falls in a
    hard-blocked range, or the host is absent from ``allowlist``.
    """
    url = (raw_url or "").strip()
    if not url:
        raise OutboundURLNotAllowed("empty URL")

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise OutboundURLNotAllowed(f"scheme '{parsed.scheme}' is not allowed; use http or https")

    host = (parsed.hostname or "").lower()
    if not host:
        raise OutboundURLNotAllowed("URL has no host")

    if _is_hard_blocked(host):
        raise OutboundURLNotAllowed(f"host '{host}' is in a blocked range")

    allowed = {entry.strip().lower() for entry in allowlist if entry and entry.strip()}
    if host not in allowed:
        raise OutboundURLNotAllowed(f"host '{host}' is not in the outbound allow-list")

    return url


def validate_db_host(host: str) -> str:
    """Validate a database host for outbound connections.

    Returns the normalized (lower-cased, trimmed) host. Database hosts are
    user-supplied by design, so this enforces only a block-list of dangerous IP
    ranges rather than a strict allow-list.
    """
    normalized = (host or "").strip().lower()
    if not normalized:
        raise OutboundURLNotAllowed("empty host")
    if _is_hard_blocked(normalized):
        raise OutboundURLNotAllowed(f"host '{normalized}' is in a blocked range")
    return normalized
