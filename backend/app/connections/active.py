from __future__ import annotations

_active_dsn: str | None = None


def get_active_dsn() -> str | None:
    return _active_dsn


def set_active_dsn(dsn: str | None) -> None:
    global _active_dsn
    _active_dsn = dsn
