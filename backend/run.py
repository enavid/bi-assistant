from __future__ import annotations

import argparse

import uvicorn

from app.core.config import settings
from app.core.logging import _RequestIdFilter


def _log_config() -> dict:
    level = settings.log_level.upper()
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": _RequestIdFilter},
        },
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)-8s %(name)s [%(request_id)s] %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "standard",
                "filters": ["request_id"],
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["console"], "propagate": False},
            "uvicorn.error": {"handlers": ["console"], "propagate": False},
            "uvicorn.access": {"level": "WARNING", "handlers": [], "propagate": False},
            "sqlalchemy.engine": {"level": "WARNING", "handlers": [], "propagate": False},
        },
        "root": {"handlers": ["console"], "level": level},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="BI Assistant API server")
    parser.add_argument("--reload", action="store_true", help="Enable hot reload")
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=args.reload,
        log_config=_log_config(),
    )


if __name__ == "__main__":
    main()
