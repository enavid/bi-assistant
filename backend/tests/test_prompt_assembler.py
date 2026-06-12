"""Tests for PromptAssembler — TDD."""

from __future__ import annotations

from app.domain.entities.workspace import Project, Section
from app.use_cases.workspace.prompt_assembler import PromptAssembler


def _section(id: str, content: str, order: int = 0) -> Section:
    return Section(id=id, name="s", content=content, order=order)


def _project(sections: list[Section], output_format: str = "") -> Project:
    return Project(
        id="p1", workspace_id="ws1", name="test", description="", notes="",
        output_format=output_format, sections=sections,
    )


assembler = PromptAssembler()


def test_assemble_without_output_format_joins_sections_in_order():
    p = _project([_section("a", "CONTEXT A", order=1), _section("b", "CONTEXT B", order=0)])
    result = assembler.assemble(p, "سوال؟")
    assert result.index("CONTEXT B") < result.index("CONTEXT A")


def test_assemble_without_output_format_appends_question():
    p = _project([_section("a", "CONTEXT")])
    result = assembler.assemble(p, "سوال؟")
    assert "سوال؟" in result
    assert "SQL:" in result


def test_assemble_with_output_format_substitutes_section_ids():
    p = _project(
        sections=[_section("sec1", "محتوای بخش اول")],
        output_format="{sec1}\n\nSEPARATOR\n\nQ: {question}",
    )
    result = assembler.assemble(p, "سوال؟")
    assert "محتوای بخش اول" in result
    assert "سوال؟" in result
    assert "{sec1}" not in result
    assert "{question}" not in result


def test_assemble_with_output_format_missing_section_leaves_placeholder():
    p = _project(
        sections=[],
        output_format="{missing_id}\n{question}",
    )
    result = assembler.assemble(p, "سوال؟")
    assert "{missing_id}" in result
    assert "سوال؟" in result


def test_assemble_skips_empty_sections_without_output_format():
    p = _project([_section("a", ""), _section("b", "محتوا")])
    result = assembler.assemble(p, "سوال؟")
    assert result.count("\n\n") < 3


def test_assemble_empty_project_returns_question_block():
    p = _project([])
    result = assembler.assemble(p, "سوال؟")
    assert "سوال؟" in result
