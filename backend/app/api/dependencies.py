from __future__ import annotations

from functools import lru_cache

from app.infrastructure.llm.ollama_client import OllamaClient
from app.infrastructure.hr_db.executor import HRQueryExecutor
from app.use_cases.chat.prompt_assembler import PromptAssembler
from app.use_cases.chat.generate_sql import GenerateSQLUseCase
from app.use_cases.chat.run_query import RunQueryUseCase


@lru_cache(maxsize=1)
def get_llm_client() -> OllamaClient:
    return OllamaClient()


@lru_cache(maxsize=1)
def get_query_executor() -> HRQueryExecutor:
    return HRQueryExecutor()


@lru_cache(maxsize=1)
def get_prompt_assembler() -> PromptAssembler:
    return PromptAssembler()


@lru_cache(maxsize=1)
def get_generate_sql_use_case() -> GenerateSQLUseCase:
    return GenerateSQLUseCase(
        llm=get_llm_client(),
        assembler=get_prompt_assembler(),
    )


@lru_cache(maxsize=1)
def get_run_query_use_case() -> RunQueryUseCase:
    return RunQueryUseCase(executor=get_query_executor())


@lru_cache(maxsize=1)
def get_hr_bi_orchestrator():
    from app.core.config import settings
    from app.infrastructure.metadata.loader import get_metadata
    from app.services.hr_bi.domain_classifier import DomainClassifier
    from app.services.hr_bi.gap_service import GapService
    from app.services.hr_bi.intent_parser import IntentParser
    from app.services.hr_bi.llm_orchestrator import LLMOrchestrator
    from app.services.hr_bi.query_executor import QueryExecutor
    from app.services.hr_bi.question_validator import QuestionValidator
    from app.services.hr_bi.response_builder import ResponseBuilder
    from app.services.hr_bi.router import DecisionRouter
    from app.services.hr_bi.semantic_mapper import SemanticMapper
    from app.services.hr_bi.sql_generator import SQLGenerator
    from app.services.hr_bi.sql_template_engine import SQLTemplateEngine
    from app.services.hr_bi.sql_validator import SQLValidator

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
