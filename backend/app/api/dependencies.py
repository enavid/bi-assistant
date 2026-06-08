from __future__ import annotations

from functools import lru_cache

from app.infrastructure.hr_db.executor import HRQueryExecutor
from app.infrastructure.llm.ollama_client import OllamaClient
from app.use_cases.workspace.run_query import RunQueryUseCase


@lru_cache(maxsize=1)
def get_llm_client() -> OllamaClient:
    return OllamaClient()


@lru_cache(maxsize=1)
def get_query_executor() -> HRQueryExecutor:
    return HRQueryExecutor()


@lru_cache(maxsize=1)
def get_run_query_use_case() -> RunQueryUseCase:
    return RunQueryUseCase(executor=get_query_executor())


@lru_cache(maxsize=1)
def get_hr_bi_orchestrator():
    from app.adapters.presenters.response_builder import ResponseBuilder
    from app.core.config import settings
    from app.infrastructure.hr_db.analytics_executor import QueryExecutor
    from app.infrastructure.metadata.loader import get_metadata
    from app.use_cases.hr_analytics.orchestrator import LLMOrchestrator
    from app.use_cases.hr_analytics.sql.generator import SQLGenerator
    from app.use_cases.hr_analytics.sql.template_engine import SQLTemplateEngine
    from app.use_cases.hr_analytics.sql.validator import SQLValidator
    from app.use_cases.hr_analytics.steps.decision_router import DecisionRouter
    from app.use_cases.hr_analytics.steps.domain_classifier import DomainClassifier
    from app.use_cases.hr_analytics.steps.gap_service import GapService
    from app.use_cases.hr_analytics.steps.intent_parser import IntentParser
    from app.use_cases.hr_analytics.steps.question_validator import QuestionValidator
    from app.use_cases.hr_analytics.steps.semantic_mapper import SemanticMapper

    metadata = get_metadata()
    sql_validator = SQLValidator(metadata_service=metadata)

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
            database_url=settings.hr_db_dsn,
        ),
        gap_service=GapService(metadata_service=metadata),
        response_builder=ResponseBuilder(metadata_service=metadata),
        default_execute_sql=settings.default_execute_sql,
        current_shamsi_year=settings.current_shamsi_year,
        strict_metadata=True,
    )
