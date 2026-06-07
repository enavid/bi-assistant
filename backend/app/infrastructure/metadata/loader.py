from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.core.config import settings


@lru_cache(maxsize=1)
def get_metadata():
    from app.services.hr_bi.metadata_service import get_metadata_service
    metadata_dir = Path(settings.metadata_dir)
    return get_metadata_service(reload=False, metadata_dir=metadata_dir, strict=True)
