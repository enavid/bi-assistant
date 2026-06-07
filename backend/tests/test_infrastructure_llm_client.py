from __future__ import annotations

from app.infrastructure.llm.analytics_client import LLMClient, LLMClientConfig, LLMResult


def test_llm_client_not_configured_when_provider_none():
    client = LLMClient(LLMClientConfig(provider="none"))
    assert client.is_configured is False


def test_llm_client_generate_sql_returns_not_configured():
    client = LLMClient(LLMClientConfig(provider="none"))
    result = client.generate_sql("count employees")
    assert isinstance(result, LLMResult)
    assert result.status == "LLM_NOT_CONFIGURED"
    assert result.sql is None


def test_llm_client_extract_sql_from_fenced_block():
    text = "```sql\nSELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v;\n```"
    sql = LLMClient.extract_sql(text)
    assert sql is not None
    assert "SELECT" in sql


def test_llm_client_extract_sql_returns_none_for_empty():
    assert LLMClient.extract_sql("") is None
    assert LLMClient.extract_sql(None) is None


def test_llm_client_extract_sql_finds_select():
    text = "Here is the SQL:\nSELECT COUNT(v.employee_id) FROM hr_mvp.vw_hr_employee_analytics v;"
    sql = LLMClient.extract_sql(text)
    assert sql is not None
    assert sql.startswith("SELECT")


def test_llm_client_extract_sql_ignores_non_sql():
    text = "I cannot generate SQL for this request because it's out of scope."
    sql = LLMClient.extract_sql(text)
    assert sql is None
