from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.domain.entities import GenerationResult, Project, QueryResult


@runtime_checkable
class ILLMClient(Protocol):
    async def generate(self, prompt: str, model: str | None = None) -> GenerationResult: ...

    async def list_models(self) -> list[dict[str, str]]: ...

    async def health(self) -> dict[str, Any]: ...


@runtime_checkable
class IQueryExecutor(Protocol):
    def run(self, sql: str) -> QueryResult: ...


@runtime_checkable
class IPromptAssembler(Protocol):
    def assemble(self, project: Project, question: str) -> str: ...


@runtime_checkable
class IMetadataService(Protocol):
    def get_main_view(self) -> dict[str, Any]: ...

    def get_sql_template(self, template_id: str) -> dict[str, Any] | None: ...

    def get_status_sql(self, status: str) -> str | None: ...

    def health_check(self) -> Any: ...


@runtime_checkable
class ISQLValidator(Protocol):
    def validate(self, sql: str, question: str | None = None) -> dict[str, Any]: ...


@runtime_checkable
class ILogger(Protocol):
    def info(self, message: str, **kwargs: Any) -> None: ...

    def error(self, message: str, **kwargs: Any) -> None: ...

    def warning(self, message: str, **kwargs: Any) -> None: ...
