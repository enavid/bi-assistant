from __future__ import annotations
import asyncio
import re
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from app.infrastructure.metadata.service import get_metadata_service

"""
sql_template_engine.py
----------------------
Controlled SQL template renderer for HR BI Assistant Phase 2.


Responsibility:
    - Choose the safest SQL template for the detected intent/report.
    - Collect normalized parameters from intent_parser / semantic_mapper / runtime.
    - Validate template parameters against metadata whitelists.
    - Render exactly one controlled SELECT/WITH SQL statement.

This module does NOT execute SQL and does NOT replace sql_validator.py.
It creates a SQL plan that must still pass sql_validator.py before execution.
"""



JsonDict = dict[str, Any]
_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SAFE_PARAM_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SQLTemplateEngineError(RuntimeError):
    """Base exception for SQL template planning/rendering errors."""


class SQLTemplateNotFoundError(SQLTemplateEngineError):
    """Raised when no SQL template can be resolved for an SQL route."""


class SQLTemplateParameterError(SQLTemplateEngineError):
    """Raised when normalized parameters are missing or unsafe."""


@dataclass
class SQLTemplateEngineConfig:
    """Runtime configuration for SQLTemplateEngine."""

    current_shamsi_year: int = 1404
    strict_parameter_validation: bool = True
    allow_status_sql: bool = True
    source_name: str = "sql_template_engine"


@dataclass
class SQLTemplatePlan:
    status: str
    route: str
    source: str
    sql: str | None = None
    intent: str | None = None
    report_id: str | None = None
    template_id: str | None = None
    resolved_template_id: str | None = None
    params: JsonDict = field(default_factory=dict)
    result_columns: list[JsonDict] = field(default_factory=list)
    output_type: str | None = None
    visualization_hint: str | None = None
    can_execute_sql: bool = False
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return asdict(self)


class SQLTemplateEngine:
    """
    Build a controlled SQL plan from metadata templates.

    The orchestrator can call any of these methods:
        build(context=..., metadata=...)
        plan(context=..., metadata=...)
        render(context=..., metadata=...)
        run(context=..., metadata=...)
        arun(context=..., metadata=...)
        __call__(context=..., metadata=...)
    """

    STATUS_ROUTES = {"GAP", "REJECT", "NEEDS_CLARIFICATION"}
    STATUS_VALUES = {
        "DATA_GAP",
        "ACCESS_DENIED",
        "OUT_OF_SCOPE",
        "NEEDS_CLARIFICATION",
        "SQL_VALIDATION_FAILED",
    }

    def __init__(
        self,
        metadata_service: Any | None = None,
        *,
        metadata_dir: str | Path | None = None,
        current_shamsi_year: int | None = None,
        strict_parameter_validation: bool = True,
    ) -> None:
        if metadata_service is not None:
            self.metadata = metadata_service
        elif get_metadata_service is not None:
            self.metadata = get_metadata_service(
                metadata_dir=metadata_dir, strict=False)
        else:
            self.metadata = None

        default_year = current_shamsi_year or self._read_default_current_shamsi_year(
            self.metadata) or 1404
        self.config = SQLTemplateEngineConfig(
            current_shamsi_year=int(default_year),
            strict_parameter_validation=strict_parameter_validation,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        *,
        context: Any | None = None,
        question: str | None = None,
        metadata: Any | None = None,
        intent_result: Mapping[str, Any] | None = None,
        route_result: Mapping[str, Any] | None = None,
        semantic_result: Mapping[str, Any] | None = None,
        runtime_params: Mapping[str, Any] | None = None,
        template_id: str | None = None,
        **kwargs: Any,
    ) -> JsonDict:
        service = metadata or self.metadata
        if service is None:
            return SQLTemplatePlan(
                status="METADATA_ERROR",
                route="REJECT",
                source=self.config.source_name,
                reason="Metadata service is not available.",
                errors=["Metadata service is not available."],
            ).to_dict()

        intent_payload = self._payload_from(
            context, "intent_result", intent_result)
        route_payload = self._payload_from(
            context, "route_result", route_result)
        semantic_payload = self._payload_from(
            context, "semantic_result", semantic_result)
        runtime_payload = self._runtime_params_from(
            context, runtime_params, kwargs)
        normalized_question = question or self._get_context_value(
            context, "normalized_question") or self._get_context_value(context, "question")

        status_plan = self._maybe_status_plan(
            service, route_payload, intent_payload)
        if status_plan is not None:
            return status_plan.to_dict()

        intent_id = self._first_non_empty(
            intent_payload.get("intent"),
            intent_payload.get("intent_id"),
            route_payload.get("intent"),
            route_payload.get("intent_id"),
        )
        report_id = self._first_non_empty(
            route_payload.get("report_id"),
            intent_payload.get("report_id"),
        )

        resolved_template_id = self._resolve_template_id(
            service,
            explicit_template_id=template_id,
            route_payload=route_payload,
            intent_payload=intent_payload,
            intent_id=str(intent_id) if intent_id else None,
            report_id=str(report_id) if report_id else None,
        )

        if not resolved_template_id:
            return SQLTemplatePlan(
                status="NO_TEMPLATE",
                route="SQL",
                source=self.config.source_name,
                intent=str(intent_id) if intent_id else None,
                report_id=str(report_id) if report_id else None,
                can_execute_sql=False,
                reason="No SQL template could be resolved for the detected SQL intent.",
                warnings=["No SQL template was found; do not execute SQL."],
                metadata={"question": normalized_question},
            ).to_dict()

        template = self._get_sql_template(service, resolved_template_id)
        if not template:
            return SQLTemplatePlan(
                status="NO_TEMPLATE",
                route="SQL",
                source=self.config.source_name,
                intent=str(intent_id) if intent_id else None,
                report_id=str(report_id) if report_id else None,
                template_id=str(resolved_template_id),
                can_execute_sql=False,
                reason=f"SQL template '{resolved_template_id}' was referenced but not found in metadata.",
                errors=[f"Missing SQL template: {resolved_template_id}"],
                metadata={"question": normalized_question},
            ).to_dict()

        params = self._collect_params(
            service=service,
            template=template,
            intent_payload=intent_payload,
            semantic_payload=semantic_payload,
            runtime_payload=runtime_payload,
        )
        validation_errors, validation_warnings = self._validate_template_params(
            service, template, params)
        if validation_errors:
            return SQLTemplatePlan(
                status="PARAMETER_VALIDATION_FAILED",
                route="SQL",
                source=self.config.source_name,
                intent=str(intent_id or template.get("intent") or "") or None,
                report_id=str(report_id or template.get(
                    "report_id") or "") or None,
                template_id=str(template.get("template_id")
                                or resolved_template_id),
                resolved_template_id=str(template.get(
                    "template_id") or resolved_template_id),
                params=self._redact_params(params),
                can_execute_sql=False,
                reason="SQL template parameters failed validation.",
                warnings=validation_warnings,
                errors=validation_errors,
                metadata={"question": normalized_question},
            ).to_dict()

        try:
            sql = self.render_sql_text(
                str(template.get("sql", "")), params, template=template)
        except SQLTemplateEngineError as exc:
            return SQLTemplatePlan(
                status="TEMPLATE_RENDER_FAILED",
                route="SQL",
                source=self.config.source_name,
                intent=str(intent_id or template.get("intent") or "") or None,
                report_id=str(report_id or template.get(
                    "report_id") or "") or None,
                template_id=str(template.get("template_id")
                                or resolved_template_id),
                resolved_template_id=str(template.get(
                    "template_id") or resolved_template_id),
                params=self._redact_params(params),
                can_execute_sql=False,
                reason=str(exc),
                warnings=validation_warnings,
                errors=[str(exc)],
                metadata={"question": normalized_question},
            ).to_dict()

        lightweight_errors = self._lightweight_sql_safety_check(sql)
        if lightweight_errors:
            return SQLTemplatePlan(
                status="SQL_TEMPLATE_UNSAFE",
                route="SQL",
                source=self.config.source_name,
                sql=sql,
                intent=str(intent_id or template.get("intent") or "") or None,
                report_id=str(report_id or template.get(
                    "report_id") or "") or None,
                template_id=str(template.get("template_id")
                                or resolved_template_id),
                resolved_template_id=str(template.get(
                    "template_id") or resolved_template_id),
                params=self._redact_params(params),
                result_columns=deepcopy(
                    template.get("result_columns", []) or []),
                output_type=template.get("output_type"),
                can_execute_sql=False,
                reason="Rendered SQL failed lightweight template safety checks.",
                warnings=validation_warnings,
                errors=lightweight_errors,
                metadata={"question": normalized_question},
            ).to_dict()

        return SQLTemplatePlan(
            status="OK",
            route="SQL",
            source=self.config.source_name,
            sql=sql,
            intent=str(intent_id or template.get("intent") or "") or None,
            report_id=str(report_id or template.get(
                "report_id") or "") or None,
            template_id=str(template.get("template_id")
                            or resolved_template_id),
            resolved_template_id=str(template.get(
                "template_id") or resolved_template_id),
            params=self._redact_params(params),
            result_columns=deepcopy(template.get("result_columns", []) or []),
            output_type=template.get("output_type"),
            visualization_hint=template.get(
                "recommended_visualization") or template.get("output_type"),
            can_execute_sql=True,
            reason="SQL was rendered from a controlled metadata template.",
            warnings=validation_warnings,
            metadata={
                "question": normalized_question,
                "template_title_fa": template.get("title_fa"),
                "template_status": template.get("status"),
                "required_columns": template.get("required_columns", []),
            },
        ).to_dict()

    def plan(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    def render(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    def run(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    async def arun(self, **kwargs: Any) -> JsonDict:
        return await asyncio.to_thread(self.build, **kwargs)

    def __call__(self, **kwargs: Any) -> JsonDict:
        return self.build(**kwargs)

    # ------------------------------------------------------------------
    # Template resolution
    # ------------------------------------------------------------------

    def _maybe_status_plan(self, service: Any, route_payload: JsonDict, intent_payload: JsonDict) -> SQLTemplatePlan | None:
        route = str(route_payload.get("route")
                    or intent_payload.get("route") or "").upper()
        status = str(route_payload.get("status")
                     or intent_payload.get("status") or "").upper()
        if route not in self.STATUS_ROUTES and status not in self.STATUS_VALUES:
            return None

        status = self._normalize_status(status=status, route=route)
        sql = self._get_status_sql(
            service, status) if self.config.allow_status_sql else None
        return SQLTemplatePlan(
            status=status,
            route=route if route in self.STATUS_ROUTES else self._route_for_status(
                status),
            source=self.config.source_name,
            sql=sql,
            intent=self._first_non_empty(intent_payload.get(
                "intent"), intent_payload.get("intent_id")),
            report_id=self._first_non_empty(route_payload.get(
                "report_id"), intent_payload.get("report_id")),
            can_execute_sql=False,
            reason=route_payload.get("reason") or intent_payload.get(
                "reason") or f"Route/status resolved as {status} before SQL planning.",
            warnings=[
                "Status SQL is returned only as a controlled status marker; business SQL must not be executed."],
        )

    @staticmethod
    def _normalize_status(*, status: str, route: str) -> str:
        if status in SQLTemplateEngine.STATUS_VALUES:
            return status
        if route == "GAP":
            return "DATA_GAP"
        if route == "NEEDS_CLARIFICATION":
            return "NEEDS_CLARIFICATION"
        if route == "REJECT":
            return "ACCESS_DENIED"
        return "SQL_VALIDATION_FAILED"

    @staticmethod
    def _route_for_status(status: str) -> str:
        if status == "DATA_GAP":
            return "GAP"
        if status == "NEEDS_CLARIFICATION":
            return "NEEDS_CLARIFICATION"
        return "REJECT"

    def _resolve_template_id(
        self,
        service: Any,
        *,
        explicit_template_id: str | None,
        route_payload: JsonDict,
        intent_payload: JsonDict,
        intent_id: str | None,
        report_id: str | None,
    ) -> str | None:
        candidates = [
            explicit_template_id,
            route_payload.get("sql_template_id"),
            route_payload.get("template_id"),
            intent_payload.get("sql_template_id"),
            intent_payload.get("template_id"),
        ]

        for candidate in candidates:
            if candidate:
                return self._resolve_sql_template_alias(service, str(candidate))

        if intent_id and hasattr(service, "build_metadata_context_for_intent"):
            try:
                metadata_context = service.build_metadata_context_for_intent(intent_id) or {
                }
                template = metadata_context.get("sql_template") or {}
                template_id = template.get("template_id") or (
                    metadata_context.get("intent") or {}).get("sql_template_id")
                if template_id:
                    return self._resolve_sql_template_alias(service, str(template_id))
            except Exception:
                pass

        if report_id and hasattr(service, "get_report"):
            report = service.get_report(report_id) or {}
            template_id = report.get("sql_template_id")
            if template_id:
                return self._resolve_sql_template_alias(service, str(template_id))

        if intent_id and hasattr(service, "list_sql_templates"):
            for template in service.list_sql_templates():
                if str(template.get("intent")) == str(intent_id):
                    return self._resolve_sql_template_alias(service, str(template.get("template_id")))

        return None

    @staticmethod
    def _resolve_sql_template_alias(service: Any, template_id: str) -> str:
        if hasattr(service, "resolve_sql_template_id"):
            try:
                return str(service.resolve_sql_template_id(template_id))
            except Exception:
                return template_id
        return template_id

    @staticmethod
    def _get_sql_template(service: Any, template_id: str) -> JsonDict | None:
        if hasattr(service, "get_sql_template"):
            template = service.get_sql_template(template_id)
            return deepcopy(template) if template else None
        if isinstance(service, dict):
            templates = ((service.get("sql_templates") or {}).get("templates") or [
            ]) if isinstance(service.get("sql_templates"), dict) else []
            for template in templates:
                if isinstance(template, dict) and str(template.get("template_id")) == template_id:
                    return deepcopy(template)
        return None

    @staticmethod
    def _get_status_sql(service: Any, status: str) -> str | None:
        if hasattr(service, "get_status_sql"):
            try:
                return service.get_status_sql(status)
            except Exception:
                return None
        if isinstance(service, dict):
            status_templates = ((service.get("sql_templates") or {}).get(
                "status_templates") or []) if isinstance(service.get("sql_templates"), dict) else []
            for item in status_templates:
                if isinstance(item, dict) and str(item.get("status", "")).upper() == status:
                    sql = item.get("sql")
                    return str(sql).strip() if sql else None
        return None

    # ------------------------------------------------------------------
    # Parameter collection and validation
    # ------------------------------------------------------------------

    def _collect_params(
        self,
        *,
        service: Any,
        template: JsonDict,
        intent_payload: JsonDict,
        semantic_payload: JsonDict,
        runtime_payload: JsonDict,
    ) -> JsonDict:
        params: JsonDict = {}

        current_year = self._first_non_empty(
            runtime_payload.get("current_shamsi_year"),
            intent_payload.get("current_shamsi_year"),
            semantic_payload.get("current_shamsi_year"),
            self._read_default_current_shamsi_year(service),
            self.config.current_shamsi_year,
        )
        params["current_shamsi_year"] = int(current_year)

        for payload in (semantic_payload.get("params", {}), intent_payload.get("params", {}), runtime_payload):
            if isinstance(payload, Mapping):
                params.update({str(k): v for k, v in payload.items()})

        # Convert normalized filters into known template parameters when parser did
        # not already provide them explicitly.
        filters = []
        for payload in (semantic_payload, intent_payload):
            value = payload.get("filters")
            if isinstance(value, list):
                filters.extend(
                    [item for item in value if isinstance(item, dict)])
        self._merge_filter_params(params, filters)

        # Apply parameter defaults from template metadata.
        for spec in template.get("parameters", []) or []:
            if not isinstance(spec, dict):
                continue
            name = spec.get("name")
            if not name:
                continue
            name = str(name)
            if name not in params and "default" in spec:
                params[name] = self._normalize_default_value(
                    spec.get("default"))
            if name not in params and spec.get("required") is False:
                params[name] = None

        # Keep only safe parameter names.
        return {key: value for key, value in params.items() if _SAFE_PARAM_NAME_RE.fullmatch(key)}

    @staticmethod
    def _merge_filter_params(params: JsonDict, filters: list[JsonDict]) -> None:
        for item in filters:
            column = str(item.get("column") or "")
            operator = str(item.get("operator") or "")
            value = item.get("value")

            if column in {"gender", "education_title", "employment_type", "contract_type"} and value is not None:
                key_by_column = {
                    "gender": "gender_value",
                    "education_title": "education_title",
                    "employment_type": "employment_type",
                    "contract_type": "contract_type",
                }
                params.setdefault(key_by_column[column], value)

            if column == "age":
                if operator in {">=", ">"} and value is not None:
                    try:
                        numeric = int(value)
                    except Exception:
                        continue
                    params.setdefault(
                        "age_min", numeric if operator == ">=" else numeric + 1)
                elif operator == "<" and value is not None:
                    try:
                        params.setdefault("age_max_exclusive", int(value))
                    except Exception:
                        continue
                elif operator == "<=" and value is not None:
                    try:
                        params.setdefault("age_max_inclusive", int(value))
                    except Exception:
                        continue
                elif operator.upper() == "BETWEEN" and isinstance(value, (list, tuple)) and len(value) == 2:
                    try:
                        params.setdefault("age_min", int(value[0]))
                        params.setdefault("age_max_inclusive", int(value[1]))
                    except Exception:
                        continue

    @staticmethod
    def _normalize_default_value(value: Any) -> Any:
        if isinstance(value, str) and value.upper() == "NULL":
            return None
        return value

    def _validate_template_params(self, service: Any, template: JsonDict, params: JsonDict) -> tuple[list[str], list[str]]:
        errors: list[str] = []
        warnings: list[str] = []
        placeholders = set(_PLACEHOLDER_RE.findall(
            str(template.get("sql", ""))))
        specs_by_name = {
            str(spec.get("name")): spec
            for spec in (template.get("parameters", []) or [])
            if isinstance(spec, dict) and spec.get("name")
        }

        for name in placeholders:
            if name not in params:
                spec = specs_by_name.get(name, {})
                if spec.get("required") is False:
                    params[name] = None
                else:
                    errors.append(
                        f"Missing required SQL template parameter: {name}")

        for name, spec in specs_by_name.items():
            required = bool(spec.get("required"))
            if required and self._is_empty_param(params.get(name)):
                errors.append(
                    f"Required SQL template parameter is empty: {name}")
                continue
            if name not in params:
                continue
            value = params.get(name)
            if self._is_empty_param(value):
                continue

            param_type = str(spec.get("type") or "").lower()
            if "integer" in param_type:
                if not self._can_be_int(value):
                    errors.append(
                        f"Parameter '{name}' must be integer or NULL; got {value!r}.")
                else:
                    numeric = int(value)
                    if name == "current_shamsi_year" and not (1300 <= numeric <= 1500):
                        errors.append(
                            "current_shamsi_year is outside expected Shamsi year range 1300..1500.")
                    if name.startswith("age_") and not (0 <= numeric <= 120):
                        errors.append(
                            f"Age parameter '{name}' is outside allowed range 0..120.")

            allowed_values = self._allowed_values_for_param(service, spec)
            if allowed_values is not None and str(value) not in {str(v) for v in allowed_values}:
                errors.append(
                    f"Parameter '{name}' value {value!r} is not in allowed values.")

        unknown_params = sorted(
            set(params) - placeholders - set(specs_by_name) - {"current_shamsi_year"})
        if unknown_params:
            warnings.append("Unused normalized parameter(s): " +
                            ", ".join(unknown_params))

        return errors, warnings

    @staticmethod
    def _is_empty_param(value: Any) -> bool:
        return value is None or value == ""

    @staticmethod
    def _can_be_int(value: Any) -> bool:
        if isinstance(value, bool):
            return False
        try:
            int(value)
            return True
        except Exception:
            return False

    def _allowed_values_for_param(self, service: Any, spec: JsonDict) -> list[Any] | None:
        if isinstance(spec.get("allowed_values"), list):
            return list(spec["allowed_values"])

        source = spec.get("allowed_values_source")
        if not source:
            return None
        source_text = str(source)
        match = re.fullmatch(
            r"data_dictionary\.([A-Za-z_][A-Za-z0-9_]*)\.allowed_values", source_text)
        if not match:
            return None
        column_name = match.group(1)
        column = self._get_column(service, column_name) or {}
        values = column.get("allowed_values")
        return list(values) if isinstance(values, list) else None

    @staticmethod
    def _get_column(service: Any, column_name: str) -> JsonDict | None:
        if hasattr(service, "get_column"):
            try:
                column = service.get_column(column_name)
                return deepcopy(column) if column else None
            except Exception:
                return None
        if isinstance(service, dict):
            columns = ((service.get("data_dictionary") or {}).get("columns") or [
            ]) if isinstance(service.get("data_dictionary"), dict) else []
            for column in columns:
                if isinstance(column, dict) and str(column.get("name")) == column_name:
                    return deepcopy(column)
        return None

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_sql_text(self, template_sql: str, params: Mapping[str, Any], *, template: JsonDict | None = None) -> str:
        if not template_sql or not template_sql.strip():
            raise SQLTemplateEngineError("SQL template text is empty.")

        rendered = template_sql.strip()
        placeholders = sorted(set(_PLACEHOLDER_RE.findall(rendered)))
        for name in placeholders:
            if not _SAFE_PARAM_NAME_RE.fullmatch(name):
                raise SQLTemplateEngineError(
                    f"Unsafe template placeholder name: {name}")
            if name not in params:
                raise SQLTemplateParameterError(
                    f"Missing SQL template parameter: {name}")
            literal = self.sql_literal(params.get(name))
            placeholder = "{" + name + "}"
            # Replace quoted placeholders first so strings do not become ''value''.
            rendered = rendered.replace("'" + placeholder + "'", literal)
            rendered = rendered.replace('"' + placeholder + '"', literal)
            rendered = rendered.replace(placeholder, literal)

        unresolved = sorted(set(_PLACEHOLDER_RE.findall(rendered)))
        if unresolved:
            raise SQLTemplateEngineError(
                "Unresolved SQL template placeholder(s): " + ", ".join(unresolved))
        return rendered

    @staticmethod
    def sql_literal(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, float):
            if value != value or value in {float("inf"), float("-inf")}:
                raise SQLTemplateParameterError(
                    "Non-finite numeric SQL parameter is not allowed.")
            return repr(value)
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (date, datetime)):
            return "'" + value.isoformat().replace("'", "''") + "'"
        if isinstance(value, (list, tuple, set)):
            return "(" + ", ".join(SQLTemplateEngine.sql_literal(item) for item in value) + ")"
        text = str(value)
        text = text.replace("\x00", "")
        text = text.replace("'", "''")
        return f"'{text}'"

    @staticmethod
    def _lightweight_sql_safety_check(sql: str) -> list[str]:
        errors: list[str] = []
        stripped = sql.strip().rstrip(";").strip()
        normalized = re.sub(r"\s+", " ", stripped).lower()

        # This is a first-pass guard only; sql_validator.py is still authoritative.
        if not (normalized.startswith("select ") or normalized.startswith("with ")):
            errors.append("Rendered SQL must start with SELECT or WITH.")
        if "hr_mvp.vw_hr_employee_analytics" not in normalized:
            # Status SQL, if any, is returned through _maybe_status_plan with can_execute_sql=False.
            errors.append(
                "Rendered SQL must use hr_mvp.vw_hr_employee_analytics.")
        if re.search(r"\bjoin\b", normalized):
            errors.append("Rendered template SQL must not contain JOIN.")
        if re.search(r"\bselect\s+\*\b", normalized):
            errors.append("Rendered template SQL must not contain SELECT *.")
        if re.search(r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|execute)\b", normalized):
            errors.append(
                "Rendered template SQL contains a blocked SQL command.")
        # Reject multiple statements except a single trailing semicolon.
        body = sql.strip()
        if ";" in body.rstrip(";"):
            errors.append("Rendered SQL must contain exactly one statement.")
        return errors

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _payload_from(context: Any | None, attr: str, explicit: Mapping[str, Any] | None) -> JsonDict:
        if explicit is not None:
            return deepcopy(dict(explicit))
        value = SQLTemplateEngine._get_context_value(context, attr)
        if isinstance(value, Mapping):
            return deepcopy(dict(value))
        return {}

    @staticmethod
    def _runtime_params_from(context: Any | None, explicit: Mapping[str, Any] | None, kwargs: Mapping[str, Any]) -> JsonDict:
        params: JsonDict = {}
        value = SQLTemplateEngine._get_context_value(context, "runtime_params")
        if isinstance(value, Mapping):
            params.update(dict(value))
        if explicit is not None:
            params.update(dict(explicit))
        for key, value in kwargs.items():
            if key not in {"metadata", "context", "question", "intent_result", "route_result", "semantic_result"}:
                params[key] = value
        return params

    @staticmethod
    def _get_context_value(context: Any | None, attr: str) -> Any:
        if context is None:
            return None
        if isinstance(context, Mapping):
            return context.get(attr)
        return getattr(context, attr, None)

    @staticmethod
    def _first_non_empty(*values: Any) -> Any:
        for value in values:
            if value is not None and value != "":
                return value
        return None

    @staticmethod
    def _redact_params(params: Mapping[str, Any]) -> JsonDict:
        # These params are normalized metadata values, but keep this hook for future
        # sensitive template parameters. Do not expose arbitrary raw user text.
        sensitive_names = {"national_id", "personnel_number",
                           "first_name", "last_name", "phone_number"}
        result: JsonDict = {}
        for key, value in params.items():
            result[str(key)] = "***" if str(key).lower() in sensitive_names else value
        return result

    @staticmethod
    def _read_default_current_shamsi_year(service: Any) -> int | None:
        try:
            if hasattr(service, "get_document"):
                doc = service.get_document("sql_templates") or {}
            elif isinstance(service, dict):
                doc = service.get("sql_templates") or {}
            else:
                return None
            policy = doc.get("parameter_policy", {}
                             ) if isinstance(doc, dict) else {}
            value = policy.get("current_shamsi_year_default_for_mvp_test")
            return int(value) if value is not None else None
        except Exception:
            return None

    @staticmethod
    def to_plain_dict(value: Any) -> JsonDict:
        if isinstance(value, dict):
            return deepcopy(value)
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if hasattr(value, "dict"):
            return value.dict()
        return {"value": value}


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_engine: SQLTemplateEngine | None = None


def get_sql_template_engine(
    *,
    reload: bool = False,
    metadata_service: Any | None = None,
    metadata_dir: str | Path | None = None,
    current_shamsi_year: int | None = None,
) -> SQLTemplateEngine:
    """Return a process-wide SQLTemplateEngine singleton."""
    global _engine
    if reload or _engine is None or metadata_service is not None or metadata_dir is not None:
        _engine = SQLTemplateEngine(
            metadata_service=metadata_service,
            metadata_dir=metadata_dir,
            current_shamsi_year=current_shamsi_year,
        )
    return _engine


# ---------------------------------------------------------------------------
# Optional local smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    engine = SQLTemplateEngine(metadata_dir=Path(__file__).resolve().parent)
    examples = [
        {
            "intent_result": {"intent": "total_employee_count", "sql_template_id": "TPL_TOTAL_EMPLOYEE_COUNT"},
            "route_result": {"route": "SQL", "status": "VALID"},
        },
        {
            "intent_result": {
                "intent": "gender_percentage",
                "sql_template_id": "TPL_GENDER_PERCENTAGE",
                "params": {"gender_value": "زن"},
            },
            "route_result": {"route": "SQL", "status": "VALID"},
        },
        {
            "intent_result": {
                "intent": "employee_count_by_age_filter",
                "sql_template_id": "TPL_EMPLOYEE_COUNT_BY_AGE_FILTER",
                "params": {"age_min": 60},
            },
            "route_result": {"route": "SQL", "status": "VALID"},
        },
    ]
    for item in examples:
        print(engine.build(**item)["sql"])
        print("---")
