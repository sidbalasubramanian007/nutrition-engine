import os
import psycopg2
from dotenv import load_dotenv
from psycopg2.extensions import parse_dsn

MACROS = ["calories", "protein", "carbs", "fat", "fiber"]

load_dotenv()


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def get_connection():
    """Opens a new connection to the products database.

    Uses DATABASE_URL if set (e.g. hosted Postgres); otherwise builds the connection
    from DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD, with local defaults.

    A DATABASE_URL pointing at a non-local host gets sslmode=require unless it sets its
    own sslmode (hosted Postgres such as Neon requires SSL). Add ?sslmode=disable to the
    URL to connect to a server without SSL, e.g. a local database from inside Docker.
    """
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        params = parse_dsn(database_url)
        if "sslmode" not in params and params.get("host", "") not in LOCAL_HOSTS:
            return psycopg2.connect(database_url, sslmode="require")
        return psycopg2.connect(database_url)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "nutrition_db"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def save_plan(plan, targets):
    """
    Saves an optimizer plan and its items in one transaction (all or nothing); returns the plan id.

    plan is optimizer.optimize_meal_plan's result; targets is {"calories", "protein", "carbs", "fat"}.
    Items are matched to products by name, so every item must exist in products.
    """
    if not plan.get("items"):
        raise ValueError("Only plans with items (status 'optimal' or 'feasible') can be saved")
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:  # commits on success, rolls back on any exception
            cur.execute(
                """
                INSERT INTO plans (target_calories, target_protein, target_carbs, target_fat, penalty, status, solver)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;
                """,
                (targets["calories"], targets["protein"], targets["carbs"], targets["fat"],
                 plan["penalty"], plan["status"], plan["solver"]),
            )
            plan_id = cur.fetchone()[0]

            names = [item["name"] for item in plan["items"]]
            cur.execute("SELECT name, id FROM products WHERE name = ANY(%s);", (names,))
            product_ids = dict(cur.fetchall())
            missing = sorted(set(names) - set(product_ids))
            if missing:
                raise LookupError(f"Plan items not found in products: {missing}")

            for item in plan["items"]:
                cur.execute(
                    "INSERT INTO plan_items (plan_id, product_id, meal, servings) VALUES (%s, %s, %s, %s);",
                    (plan_id, product_ids[item["name"]], item["meal"], item["servings"]),
                )
        return plan_id
    finally:
        conn.close()


def _plan_header(row):
    plan_id, created_at, calories, protein, carbs, fat, penalty, status, solver = row
    return {
        "id": plan_id,
        "created_at": created_at,
        "targets": {"calories": float(calories), "protein": float(protein), "carbs": float(carbs), "fat": float(fat)},
        "penalty": float(penalty),
        "status": status,
        "solver": solver,
    }


PLAN_COLUMNS = "p.id, p.created_at, p.target_calories, p.target_protein, p.target_carbs, p.target_fat, p.penalty, p.status, p.solver"


def list_plans(limit=20):
    """
    The most recent saved plans, newest first, each with targets, penalty, item count and
    achieved macros (computed from the products' current macros).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {PLAN_COLUMNS}, count(i.id),
                       {", ".join(f"COALESCE(sum(i.servings * pr.{m}), 0)" for m in MACROS)}
                FROM plans p
                LEFT JOIN plan_items i ON i.plan_id = p.id
                LEFT JOIN products pr ON pr.id = i.product_id
                GROUP BY p.id
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT %s;
                """,
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    plans = []
    for row in rows:
        plan = _plan_header(row[:9])
        plan["item_count"] = row[9]
        plan["macros"] = {m: round(float(v), 1) for m, v in zip(MACROS, row[10:])}
        plans.append(plan)
    return plans


def get_plan(plan_id):
    """A saved plan with its items (joined to product name, category and per-serving macros), or None."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {PLAN_COLUMNS} FROM plans p WHERE p.id = %s;", (plan_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                f"""
                SELECT pr.name, i.meal, i.servings, pr.category, {", ".join(f"pr.{m}" for m in MACROS)}
                FROM plan_items i
                JOIN products pr ON pr.id = i.product_id
                WHERE i.plan_id = %s
                ORDER BY i.id;
                """,
                (plan_id,),
            )
            item_rows = cur.fetchall()
    finally:
        conn.close()

    plan = _plan_header(row)
    plan["items"] = [
        {"name": name, "meal": meal, "servings": servings, "category": category,
         **{m: float(v) for m, v in zip(MACROS, values)}}
        for name, meal, servings, category, *values in item_rows
    ]
    plan["macros"] = {m: round(sum(item[m] * item["servings"] for item in plan["items"]), 1) for m in MACROS}
    return plan


def delete_plan(plan_id):
    """Deletes a saved plan (its items cascade). Returns False if there was no such plan."""
    conn = get_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM plans WHERE id = %s RETURNING id;", (plan_id,))
            return cur.fetchone() is not None
    finally:
        conn.close()
