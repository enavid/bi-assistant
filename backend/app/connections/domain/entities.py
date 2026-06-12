from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from urllib.parse import quote_plus


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass
class QueryDatabase:
    name: str
    host: str
    port: int
    db_name: str
    username: str
    password: str
    id: str = field(default_factory=_uid)
    is_active: bool = False

    def to_dsn(self) -> str:
        user = quote_plus(self.username)
        pwd = quote_plus(self.password)
        return f"postgresql+asyncpg://{user}:{pwd}@{self.host}:{self.port}/{self.db_name}"
