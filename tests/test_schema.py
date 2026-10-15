"""
schema.sql's CHECK constraints, run against a temporary Postgres database.

Skipped unless DB env vars (DATABASE_URL or DB_*, including from .env) point at a reachable
server whose user may create databases. The temporary database is dropped afterwards.
"""
import os
import uuid

import psycopg2
import pytest
from psycopg2 import errors, extensions, sql

import db
import setup_db

DB_ENV_VARS = ["DATABASE_URL", "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]

VALID_ROW = {"name": "Test Oats", "calories": 150, "protein": 5, "carbs": 27, "fat": 3, "fiber": 4,
             "category": "staple", "max_servings": 3, "location": "Grocery",
             "meal_slots": ["breakfast"], "component_type": None}


def admin_connection():
    if not any(os.getenv(var) for var in DB_ENV_VARS):
        pytest.skip("no database configured (set DATABASE_URL or DB_* to run schema tests)")
    try:
        conn = db.get_connection()
    except psycopg2.OperationalError as e:
        pytest.skip(f"configured database not reachable: {e}")
    conn.autocommit = True
    return conn


@pytest.fixture(scope="module")
def temp_db():
    """Creates a throwaway database and points db.get_connection() at it for the module."""
    admin = admin_connection()
    name = f"nutrition_test_{uuid.uuid4().hex[:12]}"
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except errors.InsufficientPrivilege:
        admin.close()
        pytest.skip("database user can't create a temporary database")

    with pytest.MonkeyPatch.context() as mp:
        if os.getenv("DATABASE_URL"):
            mp.setenv("DATABASE_URL", extensions.make_dsn(os.environ["DATABASE_URL"], dbname=name))
        else:
            mp.setenv("DB_NAME", name)
        try:
            yield name
        finally:
            with admin.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
            admin.close()


@pytest.fixture
def conn(temp_db):
    """A connection to the temporary database with schema.sql applied; rolled back afterwards."""
    connection = db.get_connection()
    assert connection.get_dsn_parameters()["dbname"] == temp_db
    with connection.cursor() as cur, open(setup_db.SCHEMA_PATH) as f:
        cur.execute(f.read())
    connection.commit()
    yield connection
    connection.rollback()
    with connection.cursor() as cur:
        cur.execute("TRUNCATE products;")
    connection.commit()
    connection.close()


def insert(conn, **overrides):
    with conn.cursor() as cur:
        cur.execute(setup_db.UPSERT_QUERY, dict(VALID_ROW, **overrides))


def test_schema_applies_twice_and_accepts_a_valid_row(conn):
    with conn.cursor() as cur, open(setup_db.SCHEMA_PATH) as f:
        cur.execute(f.read())  # second application, as on every setup_db.py re-run
    insert(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM products")
        assert cur.fetchone()[0] == 1


@pytest.mark.parametrize("overrides, constraint", [
    ({"calories": -1}, "products_calories_nonnegative"),
    ({"protein": -0.5}, "products_protein_nonnegative"),
    ({"carbs": -10}, "products_carbs_nonnegative"),
    ({"fat": -1}, "products_fat_nonnegative"),
    ({"fiber": -2}, "products_fiber_nonnegative"),
    ({"max_servings": 0}, "products_max_servings_range"),
    ({"max_servings": 6}, "products_max_servings_range"),
    ({"category": "dessert"}, "products_category_known"),
    ({"meal_slots": []}, "products_meal_slots_valid"),
    ({"meal_slots": ["breakfast", "brunch"]}, "products_meal_slots_valid"),
])
def test_invalid_insert_is_rejected(conn, overrides, constraint):
    with pytest.raises(errors.CheckViolation) as excinfo:
        insert(conn, **overrides)
    assert excinfo.value.diag.constraint_name == constraint


def test_invalid_update_of_an_existing_row_is_rejected(conn):
    insert(conn)
    conn.commit()
    with pytest.raises(errors.CheckViolation):
        insert(conn, max_servings=10)  # same name -> ON CONFLICT DO UPDATE path


def test_all_shipped_data_loads_under_the_constraints(temp_db, conn):
    setup_db.setup(with_seeds=True, with_trader_joes=True)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_constraint "
                    "WHERE conrelid = 'products'::regclass AND contype = 'c' AND NOT convalidated")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM products")
        assert cur.fetchone()[0] == len(setup_db.collect_products(with_seeds=True, with_trader_joes=True))


def test_setup_rolls_back_when_a_leftover_row_breaks_a_constraint(temp_db, conn):
    # A row that predates the constraints and isn't in any data source: NOT VALID lets
    # schema.sql apply, but validation after loading must fail and undo the whole run.
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE products DROP CONSTRAINT products_max_servings_range")
        insert(conn, name="Legacy Rice", max_servings=10)
    conn.commit()

    with pytest.raises(errors.CheckViolation):
        setup_db.setup()

    with conn.cursor() as cur:
        cur.execute("SELECT name FROM products ORDER BY name")
        assert [r[0] for r in cur.fetchall()] == ["Legacy Rice"]
