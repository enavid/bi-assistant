from __future__ import annotations

from app.domain.entities import (
    ChatSession,
    ExperimentEntry,
    GenerationResult,
    Message,
    Project,
    QueryResult,
    Section,
    Workspace,
)


def test_workspace_has_default_name():
    ws = Workspace()
    assert ws.name == "Default Workspace"
    assert ws.id


def test_project_has_id_and_timestamps():
    p = Project(name="HR Analytics", workspace_id="ws-1")
    assert p.name == "HR Analytics"
    assert p.id
    assert p.created_at


def test_section_created():
    s = Section(name="Overview", content="Some content", order=1)
    assert s.name == "Overview"
    assert s.id


def test_message_created():
    m = Message(role="user", session_id="sess-1", content="hello")
    assert m.role == "user"
    assert m.content == "hello"


def test_chat_session_has_empty_messages():
    s = ChatSession(model_name="test-model")
    assert s.messages == []
    assert s.title == "New chat"


def test_generation_result_success():
    r = GenerationResult(sql="SELECT 1;", success=True)
    assert r.sql == "SELECT 1;"
    assert r.success is True
    assert r.error is None


def test_generation_result_failure():
    r = GenerationResult(sql="", success=False, error="out of scope", status="OUT_OF_SCOPE")
    assert r.success is False
    assert r.error == "out of scope"
    assert r.status == "OUT_OF_SCOPE"


def test_query_result_success():
    r = QueryResult(columns=["count"], rows=[[5]], row_count=1, elapsed_ms=12.0, success=True)
    assert r.success is True
    assert r.columns == ["count"]
    assert r.row_count == 1


def test_experiment_entry_created():
    e = ExperimentEntry(question="how many?", sql_output="SELECT 1;", correct=True, elapsed_ms=5.0)
    assert e.correct is True
    assert e.id
