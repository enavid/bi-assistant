#!/usr/bin/env python3
"""
HR BI Pipeline Evaluation Runner
=================================
Runs a batch of questions through the pipeline and saves full trace results.

Usage:
    uv run python eval/run_evaluation.py --input eval/questions.json
    uv run python eval/run_evaluation.py --input eval/questions.csv --format csv
    uv run python eval/run_evaluation.py --input eval/questions.json --output results/run_01
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def _load_input(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("questions", data) if isinstance(data, dict) else data

    for i, row in enumerate(rows):
        if not row.get("question_id"):
            row["question_id"] = f"q{i + 1:03d}"
    return rows


# ---------------------------------------------------------------------------
# Result extraction
# ---------------------------------------------------------------------------


def _extract(response: Any, elapsed_ms: float, case: dict[str, Any]) -> dict[str, Any]:
    payload = response.to_dict() if hasattr(response, "to_dict") else dict(response)
    ctx = payload.get("context") or {}
    traces_raw: list[dict] = ctx.get("traces") or []
    sql_plan: dict = ctx.get("sql_plan") or {}
    query_result: dict = ctx.get("query_result") or {}
    sql_validation: dict = ctx.get("sql_validation") or {}
    viz_plan: dict = ctx.get("visualization_plan") or {}

    actual_route = payload.get("route") or ""
    actual_status = payload.get("status") or ""
    actual_intent = payload.get("detected_intent") or ""

    source = sql_plan.get("source") or ""
    template_id = sql_plan.get("template_id") or sql_plan.get("report_id") or ""
    llm_meta = sql_plan.get("metadata") or {}
    model_called = llm_meta.get("model") if isinstance(llm_meta, dict) else None

    sql_validator_status = sql_validation.get("status") or ""
    if not sql_validator_status:
        for t in traces_raw:
            if t.get("step") == "sql_validator":
                sql_validator_status = t.get("status", "")
                break

    execution_status = str(query_result.get("execution_status") or "")
    executed = execution_status == "SUCCESS"
    rows = query_result.get("rows") or []
    row_count = len(rows) if executed else None

    visualization = viz_plan.get("primary_visualization") or viz_plan.get("visualization") or ""

    trace_steps = [
        {
            "step": t.get("step"),
            "status": t.get("status"),
            "duration_ms": t.get("duration_ms"),
            "decision_by": (t.get("details") or {}).get("decision_by"),
        }
        for t in traces_raw
    ]

    total_ms = sum(t.get("duration_ms", 0) for t in traces_raw)
    total_duration_ms = round(total_ms or elapsed_ms, 2)

    expected_route = case.get("expected_route") or ""
    expected_status = case.get("expected_status") or ""
    expected_intent = case.get("expected_intent") or ""

    route_match = (actual_route == expected_route) if expected_route else None
    status_match = (actual_status == expected_status) if expected_status else None
    intent_match = (actual_intent == expected_intent) if expected_intent else None

    passed = all(v is not False for v in [route_match, status_match, intent_match])

    errors = payload.get("errors") or []

    return {
        "question_id": case.get("question_id", ""),
        "question": case.get("question", ""),
        "category": case.get("category") or None,
        "passed": passed,
        "expected_route": expected_route or None,
        "actual_route": actual_route or None,
        "route_match": route_match,
        "expected_status": expected_status or None,
        "actual_status": actual_status or None,
        "status_match": status_match,
        "expected_intent": expected_intent or None,
        "actual_intent": actual_intent or None,
        "intent_match": intent_match,
        "source": source or None,
        "model_called": model_called,
        "template_id": template_id or None,
        "sql_validator_status": sql_validator_status or None,
        "executed": executed,
        "row_count": row_count,
        "visualization": visualization or None,
        "total_duration_ms": total_duration_ms,
        "trace_steps": trace_steps,
        "error": errors[0] if errors else None,
        "warnings": payload.get("warnings") or [],
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def _run_all(cases: list[dict[str, Any]], concurrency: int = 1) -> list[dict[str, Any]]:
    from app.api.dependencies import get_hr_bi_orchestrator

    orchestrator = get_hr_bi_orchestrator()
    total = len(cases)
    results: list[dict[str, Any]] = [{}] * total
    sem = asyncio.Semaphore(concurrency)

    async def run_one(i: int, case: dict[str, Any]) -> None:
        async with sem:
            q = case.get("question", "")
            label = q[:65] + "…" if len(q) > 65 else q
            print(f"  [{i + 1:>3}/{total}] {label}", end="", flush=True)
            t0 = time.perf_counter()
            try:
                response = await orchestrator.arun(q, execute_sql=False)
                elapsed = (time.perf_counter() - t0) * 1000
                row = _extract(response, elapsed, case)
                mark = "✓" if row["passed"] else "✗"
                print(f"  {mark}  {row['total_duration_ms']:.0f}ms")
            except Exception as exc:
                elapsed = (time.perf_counter() - t0) * 1000
                row = {
                    "question_id": case.get("question_id", f"q{i + 1:03d}"),
                    "question": q,
                    "passed": False,
                    "total_duration_ms": round(elapsed, 2),
                    "error": str(exc),
                    "trace_steps": [],
                    "warnings": [],
                }
                print(f"  ✗  ERROR: {exc}")
            results[i] = row

    await asyncio.gather(*[run_one(i, case) for i, case in enumerate(cases)])
    return results


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


_CSV_FIELDS = [
    "question_id",
    "question",
    "category",
    "passed",
    "expected_route",
    "actual_route",
    "route_match",
    "expected_status",
    "actual_status",
    "status_match",
    "expected_intent",
    "actual_intent",
    "intent_match",
    "source",
    "model_called",
    "template_id",
    "sql_validator_status",
    "executed",
    "row_count",
    "visualization",
    "total_duration_ms",
    "error",
    "warnings",
    "trace_steps",
]


def _write_json(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)


def _write_csv(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flat = []
    for r in results:
        row = {k: r.get(k) for k in _CSV_FIELDS}
        row["trace_steps"] = json.dumps(r.get("trace_steps") or [], ensure_ascii=False)
        row["warnings"] = "; ".join(r.get("warnings") or [])
        flat.append(row)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _print_summary(results: list[dict]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    failed = total - passed
    avg_ms = sum(r.get("total_duration_ms", 0) for r in results) / max(total, 1)

    w = 60
    print("\n" + "─" * w)
    print(f"  Total     : {total}")
    print(f"  Passed    : {passed}  ✓")
    print(f"  Failed    : {failed}  {'✗' if failed else '—'}")
    print(f"  Avg time  : {avg_ms:.0f} ms / question")
    print("─" * w)

    if failed:
        print("\n  Failed questions:")
        for r in results:
            if not r.get("passed"):
                qid = r.get("question_id", "?")
                q = (r.get("question") or "")[:50]
                print(
                    f"    ✗ [{qid}] {q}\n"
                    f"         route : {r.get('expected_route')} → {r.get('actual_route')}\n"
                    f"         status: {r.get('expected_status')} → {r.get('actual_status')}\n"
                    f"         intent: {r.get('expected_intent')} → {r.get('actual_intent')}"
                )
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="HR BI Pipeline Evaluation Runner")
    parser.add_argument("--input", "-i", required=True, help="Input file: JSON or CSV")
    parser.add_argument(
        "--output",
        "-o",
        help="Output base path without extension (default: <input_dir>/evaluation_trace_results)",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["json", "csv", "both"],
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=1,
        help="Parallel questions (default: 1 — sequential)",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}")
        sys.exit(1)

    output_base = (
        Path(args.output) if args.output else input_path.parent / "evaluation_trace_results"
    )

    print("\n  HR BI Evaluation Runner")
    print(f"  Input      : {input_path}")
    print(f"  Output     : {output_base}.[json|csv]")
    print(f"  Concurrency: {args.concurrency}")
    print(f"  {'─' * 56}\n")

    cases = _load_input(input_path)
    print(f"  Loaded {len(cases)} questions\n")

    results = asyncio.run(_run_all(cases, concurrency=args.concurrency))

    _print_summary(results)

    if args.format in ("json", "both"):
        out = output_base.with_suffix(".json")
        _write_json(results, out)
        print(f"  Saved JSON → {out}")

    if args.format in ("csv", "both"):
        out = output_base.with_suffix(".csv")
        _write_csv(results, out)
        print(f"  Saved CSV  → {out}")

    print()


if __name__ == "__main__":
    main()
