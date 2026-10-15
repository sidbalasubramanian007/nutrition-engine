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
             "meal_slots": ["breakfast"], "component_type": None, "source": "manual"}


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
        cur.execute("TRUNCATE plan_items, plans, products;")
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
    ({"source": "wikipedia"}, "products_source_known"),
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


# --- nutrition_audit view ---

def audit_row(conn, name):
    with conn.cursor() as cur:
        cur.execute("SELECT atwater_kcal, kcal_difference, percent_error, flagged FROM nutrition_audit WHERE name = %s",
                    (name,))
        atwater, difference, error, flagged = cur.fetchone()
    return {"atwater_kcal": atwater, "kcal_difference": difference, "percent_error": error, "flagged": flagged}


def test_audit_does_not_flag_a_row_whose_macros_match_its_calories(conn):
    # 4*5 + 4*27 + 9*3 = 155
    insert(conn, name="Matching Oats", calories=155, protein=5, carbs=27, fat=3)
    row = audit_row(conn, "Matching Oats")
    assert row == {"atwater_kcal": 155, "kcal_difference": 0, "percent_error": 0, "flagged": False}


def test_audit_flags_a_row_25_percent_off(conn):
    # Macros give 4*25 = 100 kcal against a label of 80: off by 20/80 = 25%
    insert(conn, name="Underlabelled Protein", calories=80, protein=25, carbs=0, fat=0)
    row = audit_row(conn, "Underlabelled Protein")
    assert row == {"atwater_kcal": 100, "kcal_difference": -20, "percent_error": 25, "flagged": True}


def test_audit_flags_a_zero_calorie_row_with_nonzero_macros(conn):
    insert(conn, name="Free Lunch", calories=0, protein=0, carbs=10, fat=0)
    row = audit_row(conn, "Free Lunch")
    assert row == {"atwater_kcal": 40, "kcal_difference": -40, "percent_error": None, "flagged": True}


def test_setup_stores_source_and_applies_usda_overrides(temp_db, conn, small_sources):
    (small_sources / "data" / "usda_overrides.csv").write_text(
        "Name,Calories,Protein,Carbs,Fat,Fiber,Fdc_Id,Serving_Grams\nLemon Muffins,420,6,58,19,1.5,1987654,113\n")
    setup_db.setup(with_seeds=True, with_trader_joes=True)
    with conn.cursor() as cur:
        cur.execute("SELECT name, source, calories, category FROM products ORDER BY name")
        rows = [(n, s, float(c), cat) for n, s, c, cat in cur.fetchall()]
    assert rows == [("Lemon Muffins", "usda", 420.0, "bakery"),
                    ("Oats", "manual", 150.0, "staple"),
                    ("Tofu", "manual", 130.0, "lean_protein")]



# --- saved plans ---

PLAN_FOODS = [
    dict(VALID_ROW, name="Plan Oats", calories=150, protein=5, carbs=27, fat=3, fiber=4),
    dict(VALID_ROW, name="Plan Chicken", calories=165, protein=31, carbs=0, fat=3.6, fiber=0, category="lean_protein",
         meal_slots=["lunch", "dinner"]),
    dict(VALID_ROW, name="Plan Banana", calories=105, protein=1, carbs=27, fat=0, fiber=3, category="carb",
         meal_slots=["snack"]),
]
TARGETS = {"calories": 2000, "protein": 150, "carbs": 220, "fat": 60}


def optimizer_plan(**overrides):
    """A plan in optimizer.optimize_meal_plan's result shape."""
    plan = {
        "items": [
            {"name": "Plan Oats", "servings": 2, "category": "staple", "meal": "Breakfast"},
            {"name": "Plan Chicken", "servings": 3, "category": "lean_protein", "meal": "Dinner"},
            {"name": "Plan Banana", "servings": 1, "category": "carb", "meal": "Snack"},
        ],
        "macros": {}, "penalty": 1234.5, "status": "optimal", "solve_time": 0.2, "solver": "highs",
    }
    plan.update(overrides)
    return plan


@pytest.fixture
def plan_conn(conn):
    """conn with three products loaded for plans to reference."""
    for food in PLAN_FOODS:
        insert(conn, **food)
    conn.commit()
    return conn


def count(conn, table, where="TRUE", params=()):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {where}", params)
        return cur.fetchone()[0]


def test_save_and_get_round_trip(plan_conn):
    plan_id = db.save_plan(optimizer_plan(), TARGETS)
    saved = db.get_plan(plan_id)

    assert saved["id"] == plan_id
    assert saved["created_at"] is not None
    assert saved["targets"] == {"calories": 2000, "protein": 150, "carbs": 220, "fat": 60}
    assert (saved["penalty"], saved["status"], saved["solver"]) == (1234.5, "optimal", "highs")
    assert [(i["name"], i["meal"], i["servings"], i["category"]) for i in saved["items"]] == [
        ("Plan Oats", "Breakfast", 2, "staple"),
        ("Plan Chicken", "Dinner", 3, "lean_protein"),
        ("Plan Banana", "Snack", 1, "carb"),
    ]
    assert saved["items"][1] == {"name": "Plan Chicken", "meal": "Dinner", "servings": 3, "category": "lean_protein",
                                 "calories": 165, "protein": 31, "carbs": 0, "fat": 3.6, "fiber": 0}
    # 2x oats + 3x chicken + 1x banana
    assert saved["macros"] == {"calories": 900, "protein": 104, "carbs": 81, "fat": 16.8, "fiber": 11}

    listed = db.list_plans()
    assert [p["id"] for p in listed] == [plan_id]
    assert listed[0]["macros"] == saved["macros"]
    assert listed[0]["item_count"] == 3
    assert listed[0]["targets"] == saved["targets"]


def test_list_plans_is_newest_first_and_limited(plan_conn):
    ids = [db.save_plan(optimizer_plan(penalty=p), TARGETS) for p in (1, 2, 3)]
    assert [p["id"] for p in db.list_plans()] == ids[::-1]
    assert [p["id"] for p in db.list_plans(limit=2)] == ids[:0:-1]
    assert db.get_plan(max(ids) + 1000) is None


def test_failed_item_insert_rolls_back_the_whole_plan(plan_conn):
    # The plan row and the first two items insert fine; the third violates servings >= 1
    bad = optimizer_plan()
    bad["items"][2] = dict(bad["items"][2], servings=0)

    with pytest.raises(errors.CheckViolation):
        db.save_plan(bad, TARGETS)

    assert count(plan_conn, "plans") == 0
    assert count(plan_conn, "plan_items") == 0


def test_unknown_product_rolls_back_the_whole_plan(plan_conn):
    bad = optimizer_plan()
    bad["items"].append({"name": "Not A Product", "servings": 1, "category": "misc", "meal": "Snack"})

    with pytest.raises(LookupError, match="Not A Product"):
        db.save_plan(bad, TARGETS)

    assert count(plan_conn, "plans") == 0
    assert count(plan_conn, "plan_items") == 0


def test_infeasible_plan_cannot_be_saved(plan_conn):
    with pytest.raises(ValueError):
        db.save_plan(optimizer_plan(items=[], status="infeasible", penalty=None), TARGETS)
    assert count(plan_conn, "plans") == 0


def test_deleting_a_plan_cascades_to_its_items(plan_conn):
    keep = db.save_plan(optimizer_plan(), TARGETS)
    remove = db.save_plan(optimizer_plan(), TARGETS)

    with plan_conn.cursor() as cur:
        cur.execute("DELETE FROM plans WHERE id = %s", (remove,))
    plan_conn.commit()

    assert count(plan_conn, "plan_items", "plan_id = %s", (remove,)) == 0
    assert count(plan_conn, "plan_items", "plan_id = %s", (keep,)) == 3
    assert db.get_plan(remove) is None


def test_products_used_by_a_saved_plan_cannot_be_deleted(plan_conn):
    db.save_plan(optimizer_plan(), TARGETS)
    with pytest.raises(errors.ForeignKeyViolation):
        with plan_conn.cursor() as cur:
            cur.execute("DELETE FROM products WHERE name = 'Plan Banana'")


def test_delete_plan_reports_whether_it_deleted(plan_conn):
    plan_id = db.save_plan(optimizer_plan(), TARGETS)
    assert db.delete_plan(plan_id) is True
    assert db.delete_plan(plan_id) is False
    assert count(plan_conn, "plan_items", "plan_id = %s", (plan_id,)) == 0
