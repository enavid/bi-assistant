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
