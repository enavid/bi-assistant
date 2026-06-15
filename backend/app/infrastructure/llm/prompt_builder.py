from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

"""
prompt_builder.py
-----------------
Builds controlled prompts for LLM fallback paths.

Important principle:
    Do NOT pass the raw RequestContext to the model.
    Pass only a safe, minimal summary: intent, metric, filters, group_by,
    required columns, allowed view, and security constraints.
"""

JsonDict = dict[str, Any]


@dataclass
class SQLFallbackPrompt:
    prompt: str
    modular_context: JsonDict = field(default_factory=dict)
    schema_context: str = ""

    def to_dict(self) -> JsonDict:
        return asdict(self)


class PromptBuilder:
    def __init__(self, metadata_service: Any | None = None) -> None:
        self.metadata = metadata_service

    def build_sql_fallback_prompt(
        self,
        *,
        question: str,
        context: Any,
        metadata: Any | None = None,
        schema_context: str | None = None,
        suggested_sql: str | None = None,
        focused_columns: list[str] | None = None,
    ) -> SQLFallbackPrompt:
        service = metadata or self.metadata
        schema = schema_context or self._build_schema_context(
            service, focused_columns=focused_columns
        )
        modular_context = self.build_safe_modular_context(context)
        prompt = self._render_sql_prompt(
            question=question,
            schema_context=schema,
            modular_context=modular_context,
            suggested_sql=suggested_sql,
        )
        return SQLFallbackPrompt(
            prompt=prompt, modular_context=modular_context, schema_context=schema
        )

    def build_safe_modular_context(self, context: Any) -> JsonDict:
        intent = self._payload(context, "intent_result")
        semantic = self._payload(context, "semantic_result")
        route = self._payload(context, "route_result")
        validation = self._payload(context, "validation_result")

        group_by = intent.get("group_by") or route.get("group_by") or []
        filters = intent.get("filters") or semantic.get("filters") or []
        required_columns = intent.get("required_columns") or route.get("required_columns") or []
        metrics = intent.get("metrics") or []

        return {
            "detected_intent": intent.get("intent")
            or intent.get("intent_id")
            or route.get("intent"),
            "route": route.get("route") or intent.get("route") or "SQL",
            "status": route.get("status") or intent.get("status") or validation.get("status"),
            "metric": metrics[0] if metrics else self._infer_metric(intent),
            "filters": filters,
            "group_by": group_by,
            "required_columns": required_columns,
            "allowed_view": "hr_mvp.vw_hr_employee_analytics v",
            "safety_constraints": [
                "Generate exactly one PostgreSQL SELECT statement.",
                "Use only hr_mvp.vw_hr_employee_analytics v.",
                "Do not use JOIN.",
                "Do not use SELECT *.",
                "Do not query raw HR tables.",
                "Always apply v.is_active = TRUE.",
                "Return aggregated output only.",
                "Do not expose employee_id except inside COUNT(v.employee_id).",
            ],
        }

    def _render_sql_prompt(
        self,
        *,
        question: str,
        schema_context: str,
        modular_context: JsonDict,
        suggested_sql: str | None = None,
    ) -> str:
        suggested_section = (
            f"\nSUGGESTED SQL (pipeline pre-computed — verify and use if correct):\n{suggested_sql}\n"
            if suggested_sql
            else ""
        )
        return f"""
You are the SQL generator for HR BI Assistant.

Generate ONLY one PostgreSQL SQL statement.
No markdown, no explanation, no comments.

STRICT RULES:
- Use only this view: hr_mvp.vw_hr_employee_analytics v
- Do not use raw tables.
- Do not use JOIN.
- Do not use SELECT *.
- Do not use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE.
- Always include: WHERE v.is_active = TRUE
- Return only aggregated results.
- Do not expose individual employee records.
- employee_id may only be used inside COUNT(v.employee_id).
- If the question cannot be answered safely with the available columns, return:
  SELECT 'DATA_GAP' AS status;

AVAILABLE VIEW COLUMNS AND RULES:
{schema_context}

USER QUESTION:
{question}

PIPELINE CONTEXT (intent, filters, group_by extracted from question):
{self._format_modular_context(modular_context)}
{suggested_section}
SQL OUTPUT ONLY:
""".strip()

    @staticmethod
    def _format_modular_context(payload: JsonDict) -> str:
        lines: list[str] = []
        for key, value in payload.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)

    @staticmethod
    def _payload(context: Any, attr: str) -> JsonDict:
        if context is None:
            return {}
        value = getattr(context, attr, None)
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _infer_metric(intent_payload: JsonDict) -> JsonDict:
        intent = str(intent_payload.get("intent") or intent_payload.get("intent_id") or "")
        if intent == "average_age":
            return {"name": "average_age", "expression": "ROUND(AVG(v.age), 2)"}
        if intent == "average_service_years":
            return {"name": "average_service_years", "expression": "ROUND(AVG(v.service_years), 2)"}
        return {"name": intent or "unknown", "expression": None}

    @staticmethod
    def _build_schema_context(
        service: Any | None, *, focused_columns: list[str] | None = None
    ) -> str:
        if service is not None and hasattr(service, "build_schema_context_for_prompt"):
            try:
                kwargs: dict = {}
                if focused_columns is not None:
                    kwargs["column_names"] = focused_columns
                return str(service.build_schema_context_for_prompt(**kwargs))
            except Exception:
                pass
        return "View: hr_mvp.vw_hr_employee_analytics\nAlias: v\nColumns must be provided by MetadataService."


__all__ = ["PromptBuilder", "SQLFallbackPrompt"]
