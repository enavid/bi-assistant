from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

"""
metadata_service.py
-------------------
Central loader and accessor for the HR BI Assistant Phase 2 metadata layer.


Recommended metadata folder:
    backend/metadata/

Recommended normalized metadata filenames:
    data_dictionary.yaml
    intent_catalog.yaml
    report_catalog.json
    semantic_layer.yaml
    sql_templates.yaml
    sql_validator_rules.yaml
    visualization_rules.yaml
    evaluation_goldset.json
    access_policies.yaml
    kpi_catalog.yaml

The service also supports the generated template filenames, for example:
    Template_00_data_dictionary.yaml
    Template_07_HR_BI_Assistant_Evaluation.json

Runtime dependency:
    PyYAML>=6.0.2
"""

try:
    import yaml
except ImportError:  # pragma: no cover - handled at runtime with a clear error.
    yaml = None  # type: ignore[assignment]


JsonDict = dict[str, Any]
logger = logging.getLogger(__name__)


class MetadataServiceError(RuntimeError):
    """Base exception for metadata service failures."""


class MetadataFileNotFoundError(MetadataServiceError):
    """Raised when a required metadata file is missing."""


class MetadataParseError(MetadataServiceError):
    """Raised when a YAML/JSON file cannot be parsed."""


class MetadataValidationError(MetadataServiceError):
    """Raised when metadata content fails basic validation."""


@dataclass(frozen=True)
class MetadataFileSpec:
    key: str
    kind: str
    canonical_name: str
    aliases: tuple[str, ...] = ()
    required: bool = True

    @property
    def all_names(self) -> tuple[str, ...]:
        return (self.canonical_name, *self.aliases)


@dataclass
class MetadataFileStatus:
    key: str
    canonical_name: str
    path: str | None
    loaded: bool
    required: bool
    error: str | None = None


@dataclass
class MetadataHealth:
    ok: bool
    metadata_dir: str
    files: list[MetadataFileStatus] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "ok": self.ok,
            "metadata_dir": self.metadata_dir,
            "files": [status.__dict__ for status in self.files],
            "warnings": self.warnings,
            "errors": self.errors,
        }


@dataclass
class MetadataBundle:
    data_dictionary: JsonDict
    intent_catalog: JsonDict
    report_catalog: JsonDict
    semantic_layer: JsonDict
    sql_templates: JsonDict
    sql_validator_rules: JsonDict
    visualization_rules: JsonDict
    evaluation_goldset: JsonDict
    access_policies: JsonDict
    kpi_catalog: JsonDict

    def to_dict(self) -> JsonDict:
        return {
            "data_dictionary": self.data_dictionary,
            "intent_catalog": self.intent_catalog,
            "report_catalog": self.report_catalog,
            "semantic_layer": self.semantic_layer,
            "sql_templates": self.sql_templates,
            "sql_validator_rules": self.sql_validator_rules,
            "visualization_rules": self.visualization_rules,
            "evaluation_goldset": self.evaluation_goldset,
            "access_policies": self.access_policies,
            "kpi_catalog": self.kpi_catalog,
        }


METADATA_FILE_SPECS: tuple[MetadataFileSpec, ...] = (
    MetadataFileSpec(
        key="data_dictionary",
        kind="yaml",
        canonical_name="data_dictionary.yaml",
        aliases=("Template_00_data_dictionary.yaml", "Template 00 -data_dictionary.yaml"),
    ),
    MetadataFileSpec(
        key="intent_catalog",
        kind="yaml",
        canonical_name="intent_catalog.yaml",
        aliases=("Template_01_intent_catalog.yaml", "Template 01 - intent_catalog.yaml"),
    ),
    MetadataFileSpec(
        key="report_catalog",
        kind="json",
        canonical_name="report_catalog.json",
        aliases=("Template_02_report_catalog.json", "Template 02 - report_catalog.json"),
    ),
    MetadataFileSpec(
        key="semantic_layer",
        kind="yaml",
        canonical_name="semantic_layer.yaml",
        aliases=("Template_03_semantic_layer.yaml", "Template 03 - semantic_layer.yaml"),
    ),
    MetadataFileSpec(
        key="sql_templates",
        kind="yaml",
        canonical_name="sql_templates.yaml",
        aliases=("Template_04_sql_templates.yaml", "Template 04 -  sql_templates.yaml"),
    ),
    MetadataFileSpec(
        key="sql_validator_rules",
        kind="yaml",
        canonical_name="sql_validator_rules.yaml",
        aliases=("Template_05_sql_validator_rules.yaml", "Template 05 - sql_validator_rules.yaml"),
    ),
    MetadataFileSpec(
        key="visualization_rules",
        kind="yaml",
        canonical_name="visualization_rules.yaml",
        aliases=("Template_06_visualization_rules.yaml", "Template 06 - visualization_rules.yaml"),
    ),
    MetadataFileSpec(
        key="evaluation_goldset",
        kind="json",
        canonical_name="evaluation_goldset.json",
        aliases=(
            "HR_BI_Assistant_Evaluation.json",
            "Template_07_HR_BI_Assistant_Evaluation.json",
            "Template 07 - HR BI Assistant Evaluation.json",
        ),
    ),
    MetadataFileSpec(
        key="access_policies",
        kind="yaml",
        canonical_name="access_policies.yaml",
        aliases=("Template_08_access_policies.yaml", "Template 08 - access_policies.yaml"),
    ),
    MetadataFileSpec(
        key="kpi_catalog",
        kind="yaml",
        canonical_name="kpi_catalog.yaml",
        aliases=("Template_09_kpi_catalog.yaml",),
    ),
)


FALLBACK_TEMPLATE_ALIASES: dict[str, str] = {
    # Extra compatibility aliases used when older or KPI-specific names appear in metadata.
    "TPL_FEMALE_PERCENTAGE": "TPL_GENDER_PERCENTAGE",
    "TPL_MALE_PERCENTAGE": "TPL_GENDER_PERCENTAGE",
    "TPL_EMPLOYEE_COUNT_UNDER_30": "TPL_EMPLOYEES_UNDER_30",
    "TPL_EMPLOYEE_COUNT_AGE_60_PLUS": "TPL_EMPLOYEES_AGE_60_PLUS",
    "TPL_GENDER_DISTRIBUTION_BY_AGE_GROUP": "TPL_GENDER_BY_AGE_GROUP",
    "TPL_EMPLOYEE_COUNT_BY_SPECIFIC_EDUCATION": "TPL_EMPLOYEE_COUNT_BY_EDUCATION_VALUE",
    "TPL_EMPLOYEES_BELOW_REQUIRED_EDUCATION": "TPL_LOW_EDUCATION_IN_EXPERT_ROLES",
    "TPL_CONTRACTOR_COUNT": "TPL_CONTRACTOR_SHARE",
    "TPL_FORMAL_EMPLOYEE_COUNT": "TPL_EMPLOYEE_COUNT_BY_EMPLOYMENT_TYPE_VALUE",
    "TPL_CONTRACTUAL_EMPLOYEE_COUNT": "TPL_EMPLOYEE_COUNT_BY_EMPLOYMENT_TYPE_VALUE",
    "TPL_CONTRACT_TYPE_OF_RECENT_HIRES": "TPL_HIRING_BY_CONTRACT_TYPE_RECENT_YEAR",
}


class MetadataService:
    """
    Loads, validates, indexes and serves all HR BI Assistant metadata files.

    This module should be the only backend entry point for reading metadata.
    Other modules should not read YAML/JSON files directly.

    Typical usage:
        metadata = get_metadata_service()
        intent = metadata.get_intent("total_employee_count")
        template = metadata.get_sql_template("TPL_TOTAL_EMPLOYEE_COUNT")
        schema_context = metadata.build_schema_context_for_prompt()
    """

    def __init__(
        self, metadata_dir: str | Path | None = None, *, strict: bool = True, auto_load: bool = True
    ) -> None:
        self.metadata_dir = Path(metadata_dir) if metadata_dir else self._default_metadata_dir()
        self.strict = strict
        self._raw: dict[str, JsonDict] = {}
        self._resolved_paths: dict[str, Path] = {}
        self._file_statuses: list[MetadataFileStatus] = []
        self._warnings: list[str] = []

        self._columns_by_name: dict[str, JsonDict] = {}
        self._intents_by_id: dict[str, JsonDict] = {}
        self._reports_by_id: dict[str, JsonDict] = {}
        self._templates_by_id: dict[str, JsonDict] = {}
        self._template_aliases: dict[str, str] = {}
        self._kpis_by_id: dict[str, JsonDict] = {}
        self._visuals_by_intent: dict[str, JsonDict] = {}
        self._visuals_by_report: dict[str, JsonDict] = {}
        self._semantic_concepts_by_id: dict[str, JsonDict] = {}
        self._term_index: dict[str, Any] = {}

        if auto_load:
            self.reload(strict=strict)

    # ------------------------------------------------------------------
    # Load / reload
    # ------------------------------------------------------------------

    @staticmethod
    def _default_metadata_dir() -> Path:
        env_value = os.getenv("HR_BI_METADATA_DIR") or os.getenv("METADATA_DIR")
        if env_value:
            return Path(env_value)

        # backend/app/services/metadata_service.py -> backend
        backend_dir = Path(__file__).resolve().parents[2]
        candidates = [
            backend_dir / "metadata",
            backend_dir / "Metadata",
            backend_dir.parent / "metadata",
            backend_dir.parent / "Metadata",
            Path.cwd() / "metadata",
            Path("/app/metadata"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return backend_dir / "metadata"

    def reload(self, *, strict: bool | None = None) -> MetadataBundle:
        strict_mode = self.strict if strict is None else strict
        logger.info("loading metadata dir=%s strict=%s", self.metadata_dir, strict_mode)
        self._raw.clear()
        self._resolved_paths.clear()
        self._file_statuses.clear()
        self._warnings.clear()

        for spec in METADATA_FILE_SPECS:
            try:
                path = self._resolve_file(spec)
                if path is None:
                    message = f"Metadata file not found for '{spec.key}'. Tried: {', '.join(spec.all_names)}"
                    self._file_statuses.append(
                        MetadataFileStatus(
                            key=spec.key,
                            canonical_name=spec.canonical_name,
                            path=None,
                            loaded=False,
                            required=spec.required,
                            error=message,
                        )
                    )
                    if spec.required and strict_mode:
                        raise MetadataFileNotFoundError(message)
                    self._raw[spec.key] = {}
                    continue

                self._raw[spec.key] = self._read_metadata_file(path, spec)
                self._resolved_paths[spec.key] = path
                self._file_statuses.append(
                    MetadataFileStatus(
                        key=spec.key,
                        canonical_name=spec.canonical_name,
                        path=str(path),
                        loaded=True,
                        required=spec.required,
                    )
                )
            except MetadataServiceError as exc:
                self._file_statuses.append(
                    MetadataFileStatus(
                        key=spec.key,
                        canonical_name=spec.canonical_name,
                        path=None,
                        loaded=False,
                        required=spec.required,
                        error=str(exc),
                    )
                )
                if strict_mode:
                    raise
                self._raw[spec.key] = {}

        self._validate_minimum_structure(strict=strict_mode)
        self._build_indexes()
        self._cross_validate_references(strict=False)
        loaded = sum(1 for s in self._file_statuses if s.loaded)
        logger.info(
            "metadata loaded files=%d/%d warnings=%d",
            loaded,
            len(self._file_statuses),
            len(self._warnings),
        )
        return self.bundle

    def _resolve_file(self, spec: MetadataFileSpec) -> Path | None:
        for filename in spec.all_names:
            path = self.metadata_dir / filename
            if path.exists() and path.is_file():
                return path
        return None

    def _read_metadata_file(self, path: Path, spec: MetadataFileSpec) -> JsonDict:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MetadataParseError(f"Could not read {path}: {exc}") from exc

        try:
            if spec.kind == "json":
                data = json.loads(text)
            elif spec.kind == "yaml":
                if yaml is None:
                    raise MetadataParseError(
                        "PyYAML is not installed. Add PyYAML>=6.0.2 to backend/requirements.txt"
                    )
                data = yaml.safe_load(text)
            else:
                raise MetadataParseError(f"Unsupported metadata kind: {spec.kind}")
        except Exception as exc:
            raise MetadataParseError(f"Could not parse {path.name}: {exc}") from exc

        if not isinstance(data, dict):
            raise MetadataParseError(f"{path.name} must contain a top-level object/dictionary.")
        return data

    # ------------------------------------------------------------------
    # Basic validation / indexes
    # ------------------------------------------------------------------

    def _validate_minimum_structure(self, *, strict: bool) -> None:
        required_top_level_keys = {
            "data_dictionary": ["columns"],
            "intent_catalog": ["intents"],
            "report_catalog": ["reports"],
            "semantic_layer": ["semantic_concepts"],
            "sql_templates": ["templates"],
            "sql_validator_rules": ["allowed_sql", "blocked_sql"],
            "visualization_rules": ["intent_visualization_map"],
            "evaluation_goldset": ["test_cases"],
            "access_policies": ["default_policy", "roles"],
            "kpi_catalog": ["kpis"],
        }
        errors: list[str] = []
        for metadata_key, keys in required_top_level_keys.items():
            document = self._raw.get(metadata_key) or {}
            for key in keys:
                if key not in document:
                    errors.append(f"{metadata_key} is missing required top-level key: {key}")
        if errors and strict:
            raise MetadataValidationError("\n".join(errors))
        self._warnings.extend(errors)

    def _build_indexes(self) -> None:
        self._columns_by_name = self._index_by(
            self._raw.get("data_dictionary", {}).get("columns", []), "name"
        )
        self._intents_by_id = self._index_by(
            self._raw.get("intent_catalog", {}).get("intents", []), "intent_id"
        )
        self._reports_by_id = self._index_by(
            self._raw.get("report_catalog", {}).get("reports", []), "report_id"
        )
        self._templates_by_id = self._index_by(
            (self._raw.get("sql_templates", {}).get("templates", []) or [])
            + (self._raw.get("sql_templates", {}).get("status_templates", []) or []),
            "template_id",
        )
        self._template_aliases = {
            **FALLBACK_TEMPLATE_ALIASES,
            **(self._raw.get("sql_templates", {}).get("template_aliases", {}) or {}),
        }
        self._kpis_by_id = self._index_by(
            self._raw.get("kpi_catalog", {}).get("kpis", []), "kpi_id"
        )
        self._visuals_by_intent = self._index_by(
            self._raw.get("visualization_rules", {}).get("intent_visualization_map", []), "intent"
        )
        self._visuals_by_report = self._index_by(
            self._raw.get("visualization_rules", {}).get("report_visualization_map", []),
            "report_id",
        )
        self._semantic_concepts_by_id = self._index_by(
            self._raw.get("semantic_layer", {}).get("semantic_concepts", []), "concept_id"
        )
        self._term_index = (
            self._raw.get("semantic_layer", {}).get("term_index_for_semantic_mapper", {}) or {}
        )

    @staticmethod
    def _index_by(items: Any, key: str) -> dict[str, JsonDict]:
        index: dict[str, JsonDict] = {}
        if not isinstance(items, list):
            return index
        for item in items:
            if isinstance(item, dict) and item.get(key):
                index[str(item[key])] = item
        return index

    def _cross_validate_references(self, *, strict: bool) -> list[str]:
        warnings: list[str] = []

        for intent_id, intent in self._intents_by_id.items():
            template_id = intent.get("sql_template_id")
            if (
                template_id
                and self.resolve_sql_template_id(template_id) not in self._templates_by_id
            ):
                warnings.append(
                    f"Intent '{intent_id}' references missing sql_template_id '{template_id}'."
                )
            report_id = intent.get("report_id")
            if report_id and report_id not in self._reports_by_id:
                warnings.append(f"Intent '{intent_id}' references missing report_id '{report_id}'.")
            warnings.extend(
                self._missing_columns_warning(
                    "Intent", intent_id, intent.get("required_columns", [])
                )
            )

        for report_id, report in self._reports_by_id.items():
            template_id = report.get("sql_template_id")
            if (
                report.get("route") == "SQL"
                and template_id
                and self.resolve_sql_template_id(template_id) not in self._templates_by_id
            ):
                warnings.append(
                    f"Report '{report_id}' references missing sql_template_id '{template_id}'."
                )
            intent_id = report.get("intent")
            if intent_id and intent_id not in self._intents_by_id:
                warnings.append(f"Report '{report_id}' references missing intent '{intent_id}'.")
            warnings.extend(
                self._missing_columns_warning(
                    "Report", report_id, report.get("required_columns", [])
                )
            )

        for template_id, template in self._templates_by_id.items():
            warnings.extend(
                self._missing_columns_warning(
                    "SQL template", template_id, template.get("required_columns", [])
                )
            )

        for kpi_id, kpi in self._kpis_by_id.items():
            template_id = kpi.get("sql_template_id")
            if (
                kpi.get("route") == "SQL"
                and template_id
                and self.resolve_sql_template_id(template_id) not in self._templates_by_id
            ):
                warnings.append(
                    f"KPI '{kpi_id}' references missing sql_template_id '{template_id}'."
                )
            warnings.extend(
                self._missing_columns_warning("KPI", kpi_id, kpi.get("required_columns", []))
            )

        if warnings:
            self._warnings.extend(warnings)
        if warnings and strict:
            raise MetadataValidationError("\n".join(warnings))
        return warnings

    def _missing_columns_warning(
        self, entity_type: str, entity_id: str, required_columns: Any
    ) -> list[str]:
        if not isinstance(required_columns, list):
            return []
        missing = [str(col) for col in required_columns if str(col) not in self._columns_by_name]
        if not missing:
            return []
        return [f"{entity_type} '{entity_id}' references missing columns: {', '.join(missing)}."]

    # ------------------------------------------------------------------
    # Properties / health
    # ------------------------------------------------------------------

    @property
    def bundle(self) -> MetadataBundle:
        return MetadataBundle(
            data_dictionary=self._raw.get("data_dictionary", {}),
            intent_catalog=self._raw.get("intent_catalog", {}),
            report_catalog=self._raw.get("report_catalog", {}),
            semantic_layer=self._raw.get("semantic_layer", {}),
            sql_templates=self._raw.get("sql_templates", {}),
            sql_validator_rules=self._raw.get("sql_validator_rules", {}),
            visualization_rules=self._raw.get("visualization_rules", {}),
            evaluation_goldset=self._raw.get("evaluation_goldset", {}),
            access_policies=self._raw.get("access_policies", {}),
            kpi_catalog=self._raw.get("kpi_catalog", {}),
        )

    def health_check(self) -> MetadataHealth:
        errors = [status.error for status in self._file_statuses if status.error]
        ok = not errors
        return MetadataHealth(
            ok=ok,
            metadata_dir=str(self.metadata_dir),
            files=list(self._file_statuses),
            warnings=list(dict.fromkeys(self._warnings)),
            errors=[e for e in errors if e],
        )

    def get_all(self) -> JsonDict:
        return deepcopy(self.bundle.to_dict())

    def get_document(self, key: str) -> JsonDict:
        if key not in self._raw:
            raise KeyError(f"Unknown metadata document: {key}")
        return deepcopy(self._raw[key])

    # ------------------------------------------------------------------
    # Core metadata accessors
    # ------------------------------------------------------------------

    def get_main_view(self) -> JsonDict:
        view = (
            self._raw.get("data_dictionary", {}).get("main_view")
            or self._raw.get("report_catalog", {}).get("main_view")
            or {}
        )
        return deepcopy(view)

    def get_columns(self, *, include_restricted: bool = True) -> list[JsonDict]:
        columns = list(self._columns_by_name.values())
        if include_restricted:
            return deepcopy(columns)
        return deepcopy([col for col in columns if self._is_output_allowed_column(col)])

    def get_column(self, column_name: str) -> JsonDict | None:
        column = self._columns_by_name.get(column_name)
        return deepcopy(column) if column else None

    def list_intents(
        self, *, route: str | None = None, demo_ready: bool | None = None
    ) -> list[JsonDict]:
        items = list(self._intents_by_id.values())
        if route:
            items = [item for item in items if item.get("route") == route]
        if demo_ready is not None:
            items = [item for item in items if bool(item.get("demo_ready")) == demo_ready]
        return deepcopy(items)

    def get_intent(self, intent_id: str) -> JsonDict | None:
        item = self._intents_by_id.get(intent_id)
        return deepcopy(item) if item else None

    def list_reports(
        self, *, route: str | None = None, status: str | None = None, demo_only: bool = False
    ) -> list[JsonDict]:
        items = list(self._reports_by_id.values())
        if route:
            items = [item for item in items if item.get("route") == route]
        if status:
            items = [item for item in items if item.get("status") == status]
        if demo_only:
            items = [item for item in items if item.get("demo_priority") not in (None, 98, 99)]
        return deepcopy(sorted(items, key=lambda i: i.get("demo_priority", 999)))

    def get_report(self, report_id: str) -> JsonDict | None:
        item = self._reports_by_id.get(report_id)
        return deepcopy(item) if item else None

    def list_kpis(
        self, *, route: str | None = None, status: str | None = None, group_id: str | None = None
    ) -> list[JsonDict]:
        items = list(self._kpis_by_id.values())
        if route:
            items = [item for item in items if item.get("route") == route]
        if status:
            items = [item for item in items if item.get("status") == status]
        if group_id:
            items = [item for item in items if item.get("group_id") == group_id]
        return deepcopy(items)

    def get_kpi(self, kpi_id: str) -> JsonDict | None:
        item = self._kpis_by_id.get(kpi_id)
        return deepcopy(item) if item else None

    def list_sql_templates(
        self, *, route: str | None = None, status: str | None = None
    ) -> list[JsonDict]:
        items = list(self._templates_by_id.values())
        if route:
            items = [item for item in items if item.get("route") == route]
        if status:
            items = [item for item in items if item.get("status") == status]
        return deepcopy(items)

    def resolve_sql_template_id(self, template_id: str) -> str:
        current = template_id
        visited: set[str] = set()
        while current in self._template_aliases and current not in visited:
            visited.add(current)
            current = str(self._template_aliases[current])
        return current

    def get_sql_template(self, template_id: str) -> JsonDict | None:
        resolved_id = self.resolve_sql_template_id(template_id)
        item = self._templates_by_id.get(resolved_id)
        return deepcopy(item) if item else None

    def render_sql_template(
        self, template_id: str, params: Mapping[str, Any] | None = None
    ) -> str | None:
        template = self.get_sql_template(template_id)
        if not template:
            return None
        sql = str(template.get("sql", "")).strip()
        if not params:
            return sql

        rendered = sql
        for key, value in params.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key)):
                raise ValueError(f"Unsafe template parameter name: {key}")
            rendered = rendered.replace("{" + str(key) + "}", self._format_sql_literal(value))
        return rendered

    @staticmethod
    def _format_sql_literal(value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, int | float):
            return str(value)
        text = str(value).replace("'", "''")
        return f"'{text}'"

    def get_visualization_for_intent(self, intent_id: str) -> JsonDict | None:
        item = self._visuals_by_intent.get(intent_id)
        return deepcopy(item) if item else None

    def get_visualization_for_report(self, report_id: str) -> JsonDict | None:
        item = self._visuals_by_report.get(report_id)
        return deepcopy(item) if item else None

    def get_status_sql(self, status: str) -> str | None:
        normalized = status.upper().strip()
        status_map = self._raw.get("sql_validator_rules", {}).get("default_status_sql", {}) or {}
        key_by_status = {
            "DATA_GAP": "on_data_gap",
            "ACCESS_DENIED": "on_access_denied",
            "OUT_OF_SCOPE": "on_out_of_scope",
            "NEEDS_CLARIFICATION": "on_needs_clarification",
            "SQL_VALIDATION_FAILED": "on_validation_failed",
        }
        value = status_map.get(key_by_status.get(normalized, ""))
        if isinstance(value, str):
            return value

        status_templates = self._raw.get("sql_templates", {}).get("status_templates", []) or []
        for template in status_templates:
            if isinstance(template, dict) and str(template.get("status", "")).upper() == normalized:
                return str(template.get("sql", "")).strip()
        return None

    # ------------------------------------------------------------------
    # Semantic helpers
    # ------------------------------------------------------------------

    def normalize_question(self, question: str) -> str:
        text = question.strip()
        replacements = {
            "ي": "ی",
            "ك": "ک",
            "ة": "ه",
            "ۀ": "ه",
            "ؤ": "و",
            "إ": "ا",
            "أ": "ا",
            "آ": "آ",
        }
        for src, dst in replacements.items():
            text = text.replace(src, dst)
        text = re.sub(r"\s+", " ", text)
        return text

    def find_semantic_matches(self, question: str, *, max_matches: int = 20) -> list[JsonDict]:
        normalized = self.normalize_question(question)
        matches: list[JsonDict] = []

        # Prefer structured semantic_concepts because it includes maps_to details.
        for concept_id, concept in self._semantic_concepts_by_id.items():
            terms = concept.get("user_terms_fa", []) or []
            matched_terms = [
                term for term in terms if isinstance(term, str) and term and term in normalized
            ]
            if matched_terms:
                matches.append(
                    {
                        "concept_id": concept_id,
                        "title_fa": concept.get("title_fa"),
                        "category": concept.get("category"),
                        "matched_terms": matched_terms[:5],
                        "maps_to": concept.get("maps_to", {}),
                        "priority": concept.get("priority", "medium"),
                        "data_status": concept.get("data_status", "unknown"),
                    }
                )

        priority_rank = {"high": 0, "medium": 1, "low": 2}
        matches.sort(
            key=lambda item: (
                priority_rank.get(item.get("priority"), 99),
                -len(item.get("matched_terms", [])),
            )
        )
        return deepcopy(matches[:max_matches])

    def get_data_gap_semantics(self) -> JsonDict:
        semantic_layer = self._raw.get("semantic_layer", {})
        return deepcopy(
            {
                "data_gap_semantics": semantic_layer.get("data_gap_semantics", {}),
                "data_gap_rules": self._raw.get("data_dictionary", {}).get("data_gap_rules", []),
                "validator_data_gap_rules": self._raw.get("sql_validator_rules", {}).get(
                    "data_gap_rules", []
                ),
            }
        )

    # ------------------------------------------------------------------
    # Prompt/schema context helpers
    # ------------------------------------------------------------------

    _ALWAYS_INCLUDE_COLUMNS: frozenset[str] = frozenset({"employee_id", "is_active"})

    def build_schema_context_for_prompt(
        self,
        *,
        include_allowed_values: bool = True,
        include_semantics: bool = True,
        column_names: list[str] | None = None,
    ) -> str:
        """
        Build a compact text context for the SQL generator prompt.

        When column_names is provided, only those columns plus base columns
        (employee_id, is_active) are included and semantic mappings are omitted.
        This produces a focused schema (~1500-3000 chars vs ~17000 chars full).
        """
        main_view = self.get_main_view()
        view_name = (
            main_view.get("name") or main_view.get("relation") or "hr_mvp.vw_hr_employee_analytics"
        )
        alias = main_view.get("alias") or "v"

        focused = column_names is not None
        allowed_names: frozenset[str] | None = (
            frozenset(column_names) | self._ALWAYS_INCLUDE_COLUMNS if focused else None
        )

        lines: list[str] = [
            f"View: {view_name}",
            f"Alias: {alias}",
            "Description: One row represents one active employee for aggregated HR analytics.",
            "Only this View may be used. Raw HR tables, JOINs, SELECT *, and individual employee output are not allowed.",
            "",
            "Columns:",
        ]

        for column in self.get_columns(include_restricted=True):
            name = column.get("name")
            if allowed_names is not None and name not in allowed_names:
                continue

            data_type = column.get("data_type", "unknown")
            title = column.get("title_fa", "")
            description = column.get("description_fa", "")
            sensitivity = column.get("sensitivity", "")
            permissions = (
                column.get("permissions", {}) if isinstance(column.get("permissions"), dict) else {}
            )
            output_allowed = permissions.get("output_allowed")

            line = f"- {name}: {data_type}"
            if title:
                line += f", title_fa={title}"
            if sensitivity:
                line += f", sensitivity={sensitivity}"
            if output_allowed is not None:
                line += f", output_allowed={output_allowed}"
            if description:
                line += f", {description}"
            lines.append(line)

            if include_allowed_values and column.get("allowed_values"):
                allowed_values = column.get("allowed_values")
                if isinstance(allowed_values, list):
                    values = ", ".join(str(v) for v in allowed_values[:30])
                    lines.append(f"  Allowed values: {values}")

        if include_semantics and not focused:
            lines.extend(["", "Semantic mappings:"])
            semantic_concepts = (
                self._raw.get("semantic_layer", {}).get("semantic_concepts", []) or []
            )
            for concept in semantic_concepts[:80]:
                if not isinstance(concept, dict):
                    continue
                terms = concept.get("user_terms_fa", []) or []
                maps_to = concept.get("maps_to", {}) or {}
                if not terms or not maps_to:
                    continue
                mapped_column = (
                    maps_to.get("column") or maps_to.get("metric") or maps_to.get("route")
                )
                sample_terms = ", ".join(str(t) for t in terms[:8])
                lines.append(f"- {sample_terms} => {mapped_column}")

        lines.extend(
            [
                "",
                "Important rules:",
                "- Use COUNT(v.employee_id) for employee counts.",
                "- Always apply v.is_active = TRUE for SQL metrics unless the status SQL is DATA_GAP/ACCESS_DENIED/OUT_OF_SCOPE/NEEDS_CLARIFICATION.",
                "- Use NULLIF in percentage denominators.",
                "- For department approved headcount, never SUM(v.department_approved_headcount) over employee rows; use MAX at department level.",
                "- City-level, near-retirement, productivity, monthly hiring, and unavailable concepts must return DATA_GAP.",
                "- Individual employee information must return ACCESS_DENIED.",
            ]
        )
        return "\n".join(lines)

    def build_metadata_context_for_intent(self, intent_id: str) -> JsonDict:
        """
        Return the compact metadata context needed by the orchestrator for one intent.
        """
        intent = self.get_intent(intent_id)
        if not intent:
            return {"found": False, "intent_id": intent_id}

        report = self.get_report(str(intent.get("report_id"))) if intent.get("report_id") else None
        template = (
            self.get_sql_template(str(intent.get("sql_template_id")))
            if intent.get("sql_template_id")
            else None
        )
        visualization = self.get_visualization_for_intent(intent_id)

        return {
            "found": True,
            "intent": intent,
            "report": report,
            "sql_template": template,
            "visualization": visualization,
            "required_columns": intent.get("required_columns", []),
            "route": intent.get("route"),
            "status": intent.get("status"),
        }

    # ------------------------------------------------------------------
    # Policy helpers
    # ------------------------------------------------------------------

    def get_min_group_size(self, default: int = 5) -> int:
        policies = self._raw.get("access_policies", {})
        aggregation_rules = (
            policies.get("aggregation_rules", {})
            if isinstance(policies.get("aggregation_rules"), dict)
            else {}
        )
        for key in ("minimum_group_size", "min_group_size", "min_group_size_default"):
            value = aggregation_rules.get(key)
            if isinstance(value, int):
                return value
        global_rules = self._raw.get("visualization_rules", {}).get("global_rules", {}) or {}
        value = global_rules.get("min_group_size_default")
        return int(value) if isinstance(value, int | float) else default

    def get_sensitive_columns(self) -> list[str]:
        blocklist = (
            self._raw.get("sql_validator_rules", {}).get("sensitive_columns_blocklist", []) or []
        )
        access_sensitive = self._raw.get("access_policies", {}).get("sensitive_columns", []) or []
        names: list[str] = []
        for item in [*blocklist, *access_sensitive]:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                value = item.get("name") or item.get("column")
                if value:
                    names.append(str(value))
        return sorted(set(names))

    def get_allowed_output_columns(self) -> list[str]:
        return [
            str(col.get("name"))
            for col in self.get_columns(include_restricted=False)
            if col.get("name")
        ]

    @staticmethod
    def _is_output_allowed_column(column: JsonDict) -> bool:
        permissions = (
            column.get("permissions") if isinstance(column.get("permissions"), dict) else {}
        )
        if permissions.get("output_allowed") is False:
            return False
        if permissions.get("individual_output_allowed") is True:
            return False
        sensitivity = str(column.get("sensitivity", "")).lower()
        if sensitivity in {"sensitive", "high", "personal", "identifier"}:
            return False
        return True


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_service: MetadataService | None = None


def get_metadata_service(
    *, reload: bool = False, metadata_dir: str | Path | None = None, strict: bool = True
) -> MetadataService:
    """Return a process-wide MetadataService singleton."""
    global _service
    if reload or _service is None or metadata_dir is not None:
        _service = MetadataService(metadata_dir=metadata_dir, strict=strict, auto_load=True)
    return _service


def reload_metadata(
    metadata_dir: str | Path | None = None, *, strict: bool = True
) -> MetadataService:
    """Force reload metadata files from disk."""
    return get_metadata_service(reload=True, metadata_dir=metadata_dir, strict=strict)


# ---------------------------------------------------------------------------
# Optional small utility for local debugging
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    service = MetadataService(strict=False)
    print(json.dumps(service.health_check().to_dict(), ensure_ascii=False, indent=2))
    print("\nLoaded intents:", len(service.list_intents()))
    print("Loaded reports:", len(service.list_reports()))
    print("Loaded SQL templates:", len(service.list_sql_templates()))
    print("Loaded KPIs:", len(service.list_kpis()))
