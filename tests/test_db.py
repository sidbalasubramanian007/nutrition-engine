import pytest

import db

DB_ENV_VARS = ["DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]


@pytest.fixture
def connect_calls(monkeypatch):
    """Clears DB env vars and records the args db.get_connection() passes to psycopg2.connect."""
    for var in DB_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    calls = []
    monkeypatch.setattr(db.psycopg2, "connect", lambda *args, **kwargs: calls.append((args, kwargs)))
    return calls


def test_database_url_wins_over_individual_vars(monkeypatch, connect_calls):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.example.com:6543/prod")
    monkeypatch.setenv("DB_HOST", "ignored-host")
    monkeypatch.setenv("DB_NAME", "ignored_db")

    db.get_connection()

    # A remote host gets SSL by default (hosted Postgres such as Neon requires it)
    assert connect_calls == [(("postgresql://u:p@db.example.com:6543/prod",), {"sslmode": "require"})]


@pytest.mark.parametrize("url, kwargs", [
    # Neon-style URL that already asks for SSL: passed through untouched
    ("postgresql://u:p@ep-cool-name.us-east-2.aws.neon.tech/neondb?sslmode=require", {}),
    # An explicit sslmode always wins, e.g. a local database reached from inside Docker
    ("postgresql://u:p@host.docker.internal:5433/nutrition_db?sslmode=disable", {}),
    # Local hosts don't get SSL forced on them
    ("postgresql://u:p@localhost:5433/nutrition_db", {}),
    ("postgresql://u:p@127.0.0.1/nutrition_db", {}),
    # Remote host without sslmode: SSL required
    ("postgresql://u:p@ep-cool-name.us-east-2.aws.neon.tech/neondb", {"sslmode": "require"}),
])
def test_database_url_ssl_defaults(monkeypatch, connect_calls, url, kwargs):
    monkeypatch.setenv("DATABASE_URL", url)
    db.get_connection()
    assert connect_calls == [((url,), kwargs)]


def test_individual_vars_are_passed_when_database_url_unset(monkeypatch, connect_calls):
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_NAME", "staging_db")
    monkeypatch.setenv("DB_USER", "app")
    monkeypatch.setenv("DB_PASSWORD", "secret")

    db.get_connection()

    assert connect_calls == [((), {
        "host": "db.internal", "port": "6543", "dbname": "staging_db",
        "user": "app", "password": "secret",
    })]


def test_unset_vars_fall_back_to_local_defaults(connect_calls):
    db.get_connection()

    assert connect_calls == [((), {
        "host": "localhost", "port": "5432", "dbname": "nutrition_db",
        "user": None, "password": "",
    })]


def test_empty_database_url_falls_back_to_individual_vars(monkeypatch, connect_calls):
    monkeypatch.setenv("DATABASE_URL", "")

    db.get_connection()

    assert connect_calls[0][1]["host"] == "localhost"
