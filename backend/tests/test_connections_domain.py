"""Tests for connections domain entities."""

from __future__ import annotations

from app.connections.domain.entities import QueryDatabase


def test_query_database_has_id():
    db = QueryDatabase(
        name="HR Prod",
        host="localhost",
        port=5432,
        db_name="hr",
        username="user",
        password="secret",
    )
    assert db.id
    assert len(db.id) > 0


def test_query_database_defaults():
    db = QueryDatabase(
        name="Test", host="localhost", port=5432, db_name="mydb", username="u", password="p"
    )
    assert db.is_active is False
    assert db.port == 5432


def test_query_database_dsn():
    db = QueryDatabase(
        name="Test",
        host="db.example.com",
        port=5432,
        db_name="hr_db",
        username="admin",
        password="pass123",
    )
    dsn = db.to_dsn()
    assert "db.example.com" in dsn
    assert "5432" in dsn
    assert "hr_db" in dsn
    assert "admin" in dsn


def test_query_database_dsn_escapes_password():
    db = QueryDatabase(
        name="Test",
        host="localhost",
        port=5432,
        db_name="db",
        username="user",
        password="p@ss/word",
    )
    dsn = db.to_dsn()
    assert "p@ss/word" not in dsn
    assert "p%40ss%2Fword" in dsn


# ---------------------------------------------------------------------------
# active.py — active model auto-selection
# ---------------------------------------------------------------------------


def test_set_model_config_auto_selects_first_as_active():
    import app.connections.active as active

    original_configs = dict(active._model_configs)
    original_model = active._active_model
    try:
        active._model_configs.clear()
        active._active_model = None

        active.set_model_config("llama3.1:8b", {"num_ctx": 4096})
        assert active.get_active_model() == "llama3.1:8b"
    finally:
        active._model_configs.clear()
        active._model_configs.update(original_configs)
        active._active_model = original_model


def test_set_model_config_does_not_override_existing_active():
    import app.connections.active as active

    original_configs = dict(active._model_configs)
    original_model = active._active_model
    try:
        active._model_configs.clear()
        active._active_model = None

        active.set_model_config("llama3.1:8b", {"num_ctx": 4096})
        active.set_model_config("mistral:7b", {"num_ctx": 8192})
        assert active.get_active_model() == "llama3.1:8b"
    finally:
        active._model_configs.clear()
        active._model_configs.update(original_configs)
        active._active_model = original_model


def test_remove_active_model_config_selects_next():
    import app.connections.active as active

    original_configs = dict(active._model_configs)
    original_model = active._active_model
    try:
        active._model_configs.clear()
        active._active_model = None

        active.set_model_config("llama3.1:8b", {})
        active.set_model_config("mistral:7b", {})
        assert active.get_active_model() == "llama3.1:8b"

        active.remove_model_config("llama3.1:8b")
        assert active.get_active_model() == "mistral:7b"
    finally:
        active._model_configs.clear()
        active._model_configs.update(original_configs)
        active._active_model = original_model


def test_remove_last_model_config_clears_active():
    import app.connections.active as active

    original_configs = dict(active._model_configs)
    original_model = active._active_model
    try:
        active._model_configs.clear()
        active._active_model = None

        active.set_model_config("llama3.1:8b", {})
        active.remove_model_config("llama3.1:8b")
        assert active.get_active_model() is None
    finally:
        active._model_configs.clear()
        active._model_configs.update(original_configs)
        active._active_model = original_model
