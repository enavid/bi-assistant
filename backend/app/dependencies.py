from __future__ import annotations

from functools import lru_cache

from app.connections.active import get_active_dsn, get_active_ollama_base_url, get_all_model_configs
from app.infrastructure.hr_db.executor import HRQueryExecutor
from app.infrastructure.llm.ollama_client import OllamaClient
from app.workspace.use_cases.run_query import RunQueryUseCase


def _resolve_query_dsn() -> str:
    dsn = get_active_dsn()
    if not dsn:
        raise RuntimeError(
            "No active query database configured. Add and activate one in Settings → Database."
        )
    return dsn


@lru_cache(maxsize=1)
def get_llm_client() -> OllamaClient:
    base_url = get_active_ollama_base_url()
    if not base_url:
        raise RuntimeError(
            "No active Ollama connection configured. Add and activate one in Settings → Ollama."
        )
    url = base_url.rstrip("/") + "/api/generate"
    tags_url = base_url.rstrip("/") + "/api/tags"
    return OllamaClient(url=url, tags_url=tags_url, model_configs=get_all_model_configs())


@lru_cache(maxsize=1)
def get_query_executor() -> HRQueryExecutor:
    return HRQueryExecutor(dsn=_resolve_query_dsn())


@lru_cache(maxsize=1)
def get_run_query_use_case() -> RunQueryUseCase:
    return RunQueryUseCase(executor=get_query_executor())


@lru_cache(maxsize=1)
def get_hr_bi_orchestrator():
    from app.core.config import settings
    from app.hr_analytics.adapters.response_builder import ResponseBuilder
    from app.hr_analytics.use_cases.orchestrator import LLMOrchestrator
    from app.hr_analytics.use_cases.sql.generator import SQLGenerator
    from app.hr_analytics.use_cases.sql.template_engine import SQLTemplateEngine
    from app.hr_analytics.use_cases.sql.validator import SQLValidator
    from app.hr_analytics.use_cases.steps.decision_router import DecisionRouter
    from app.hr_analytics.use_cases.steps.domain_classifier import DomainClassifier
    from app.hr_analytics.use_cases.steps.gap_service import GapService
    from app.hr_analytics.use_cases.steps.intent_parser import IntentParser
    from app.hr_analytics.use_cases.steps.question_validator import QuestionValidator
    from app.hr_analytics.use_cases.steps.semantic_mapper import SemanticMapper
    from app.infrastructure.hr_db.analytics_executor import QueryExecutor
    from app.infrastructure.metadata.loader import get_metadata

    metadata = get_metadata()
    sql_validator = SQLValidator(metadata_service=metadata)

    ollama_client = None
    try:
        ollama_client = get_llm_client()
    except RuntimeError:
        pass

    return LLMOrchestrator(
        metadata_service=metadata,
        domain_classifier=DomainClassifier(),
        question_validator=QuestionValidator(),
        semantic_mapper=SemanticMapper(metadata_service=metadata),
        intent_parser=IntentParser(metadata_service=metadata),
        router=DecisionRouter(metadata_service=metadata),
        sql_template_engine=SQLTemplateEngine(metadata_service=metadata),
        sql_generator=SQLGenerator(metadata_service=metadata),
        sql_validator=sql_validator,
        query_executor=QueryExecutor(
            metadata_service=metadata,
            sql_validator=sql_validator,
            database_url=_resolve_query_dsn(),
        ),
        gap_service=GapService(metadata_service=metadata),
        response_builder=ResponseBuilder(metadata_service=metadata),
        ollama_client=ollama_client,
        default_model=settings.default_model,
        default_execute_sql=settings.default_execute_sql,
        current_shamsi_year=settings.current_shamsi_year,
        strict_metadata=True,
        use_template_engine=settings.use_template_engine,
        use_controlled_dynamic=settings.use_controlled_dynamic,
        force_llm_for_incomplete_template=settings.force_llm_for_incomplete_template,
    )
