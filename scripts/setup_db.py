"""Creates the products schema and loads the food data. Safe to re-run.

Usage (from the repo root):
    python scripts/setup_db.py                     # food_data.csv only
    python scripts/setup_db.py --with-seeds        # + curated staples in data/*.csv
    python scripts/setup_db.py --with-trader-joes  # + trader_joes_macros.json (scraper output)

Rows are upserted by name. When the same name appears in more than one source,
food_data.csv wins over the seed files, which win over the Trader Joe's data.

Meal slots come from each CSV's Meal_Slots column (e.g. "breakfast|snack"). Rows
without one (Trader Joe's items, blank cells, leftovers from older loads) get the
default rule in default_meal_slots().

Restaurant items need a Component_Type (base, protein, beans, topping or sauce),
which optimizer.optimize_restaurant_order builds orders from; grocery items leave it blank.
"""
import argparse
import csv
import glob
import json
import os
import sys

from psycopg2 import sql

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db

SCHEMA_PATH = os.path.join(ROOT, "schema.sql")
FOOD_DATA_PATH = os.path.join(ROOT, "food_data.csv")
SEED_GLOB = os.path.join(ROOT, "data", "*.csv")
TRADER_JOES_PATH = os.path.join(ROOT, "trader_joes_macros.json")

# Keyword tagging for scraped items, which carry no category of their own.
# Protein keywords are checked last so they win over bakery keywords.
BAKERY_KEYWORDS = ['Muffin', 'Bread', 'Cake', 'Blondie', 'Pretzel', 'Pancake', 'Waffle', 'Scone', 'Graham', 'Cookie', 'Tortilla', 'Brioche']
PROTEIN_KEYWORDS = ['Chicken', 'Salmon', 'Turkey', 'Yogurt', 'Tofu']

MEAL_SLOTS = ["breakfast", "lunch", "dinner", "snack"]
COMPONENT_TYPES = ["base", "protein", "beans", "topping", "sauce"]

UPSERT_QUERY = """
INSERT INTO products (name, calories, protein, carbs, fat, fiber, category, max_servings, location, meal_slots, component_type)
VALUES (%(name)s, %(calories)s, %(protein)s, %(carbs)s, %(fat)s, %(fiber)s, %(category)s, %(max_servings)s, %(location)s, %(meal_slots)s, %(component_type)s)
ON CONFLICT (name) DO UPDATE SET
    calories     = EXCLUDED.calories,
    protein      = EXCLUDED.protein,
    carbs        = EXCLUDED.carbs,
    fat          = EXCLUDED.fat,
    fiber        = EXCLUDED.fiber,
    category     = EXCLUDED.category,
    max_servings = EXCLUDED.max_servings,
    location     = EXCLUDED.location,
    meal_slots   = EXCLUDED.meal_slots,
    component_type = EXCLUDED.component_type;
"""


def default_meal_slots(category, location):
    """Restaurant items and lean proteins are lunch/dinner only; everything else fits any slot."""
    if location != "Grocery" or category == "lean_protein":
        return ["lunch", "dinner"]
    return list(MEAL_SLOTS)


def parse_meal_slots(value, category, location):
    """Parses a Meal_Slots cell like "breakfast|snack", falling back to the default rule when blank."""
    if not value or not value.strip():
        return default_meal_slots(category, location)
    slots = [slot.strip() for slot in value.split("|")]
    unknown = [slot for slot in slots if slot not in MEAL_SLOTS]
    if unknown:
        raise ValueError(f"Unknown meal slot(s) {unknown} in {value!r}; expected some of {MEAL_SLOTS}")
    return slots


def parse_component_type(value, name, location):
    """Validates a Component_Type cell: required for restaurant items, blank (None) for grocery items."""
    value = (value or "").strip()
    if not value:
        if location != "Grocery":
            raise ValueError(f"{name!r} ({location}) needs a Component_Type, one of {COMPONENT_TYPES}")
        return None
    if value not in COMPONENT_TYPES:
        raise ValueError(f"Unknown Component_Type {value!r} for {name!r}; expected one of {COMPONENT_TYPES}")
    return value


def read_food_csv(path):
    """Reads a CSV with food_data.csv's header into product dicts."""
    with open(path, newline="") as f:
        return [
            {
                "name": row["Name"],
                "calories": float(row["Calories"]),
                "protein": float(row["Protein"]),
                "carbs": float(row["Carbs"]),
                "fat": float(row["Fat"]),
                "fiber": float(row["Fiber"]),
                "category": row["Category"],
                "max_servings": int(row["Max_Servings"]),
                "location": row["Location"],
                "meal_slots": parse_meal_slots(row.get("Meal_Slots"), row["Category"], row["Location"]),
                "component_type": parse_component_type(row.get("Component_Type"), row["Name"], row["Location"]),
            }
            for row in csv.DictReader(f)
        ]


def tag_category(name):
    category = "misc"
    if any(word.lower() in name.lower() for word in BAKERY_KEYWORDS):
        category = "bakery"
    if any(word.lower() in name.lower() for word in PROTEIN_KEYWORDS):
        category = "lean_protein"
    return category


def read_trader_joes(path):
    """Reads scraper output into product dicts, tagging category by keyword and using default meal slots."""
    with open(path) as f:
        items = json.load(f)
    products = []
    for item in items:
        category = tag_category(item["name"])
        products.append({
            "name": item["name"],
            "calories": item["calories"],
            "protein": item["protein"],
            "carbs": item["carbs"],
            "fat": item["fat"],
            "fiber": item["fiber"],
            "category": category,
            "max_servings": 3,
            "location": "Grocery",
            "meal_slots": default_meal_slots(category, "Grocery"),
            "component_type": None,
        })
    return products


def collect_products(with_seeds, with_trader_joes):
    """Merges all requested sources by name, lowest priority first."""
    sources = []
    if with_trader_joes:
        if os.path.exists(TRADER_JOES_PATH):
            sources.append(("trader_joes_macros.json", read_trader_joes(TRADER_JOES_PATH)))
        else:
            print("trader_joes_macros.json not found, skipping (run scraper.py to create it).")
    if with_seeds:
        for path in sorted(glob.glob(SEED_GLOB)):
            sources.append((os.path.relpath(path, ROOT), read_food_csv(path)))
    sources.append(("food_data.csv", read_food_csv(FOOD_DATA_PATH)))

    products = {}
    for label, rows in sources:
        print(f"Loaded {len(rows)} rows from {label}")
        for row in rows:
            products[row["name"]] = row
    return list(products.values())


def backfill_meal_slots(cur):
    """Gives rows not in this run's sources (e.g. from an older load) the default meal slots."""
    cur.execute("SELECT name, category, location FROM products WHERE meal_slots IS NULL;")
    for name, category, location in cur.fetchall():
        cur.execute(
            "UPDATE products SET meal_slots = %s WHERE name = %s;",
            (default_meal_slots(category, location), name),
        )


def validate_constraints(cur):
    """Checks every row against schema.sql's CHECK constraints, which are added NOT VALID."""
    cur.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'products'::regclass AND NOT convalidated;")
    for (name,) in cur.fetchall():
        cur.execute(sql.SQL("ALTER TABLE products VALIDATE CONSTRAINT {};").format(sql.Identifier(name)))


def setup(with_seeds=False, with_trader_joes=False):
    products = collect_products(with_seeds, with_trader_joes)

    conn = db.get_connection()
    try:
        with conn, conn.cursor() as cur:
            with open(SCHEMA_PATH) as f:
                cur.execute(f.read())
            cur.executemany(UPSERT_QUERY, products)
            backfill_meal_slots(cur)
            validate_constraints(cur)
            cur.execute("SELECT count(*) FROM products;")
            total = cur.fetchone()[0]
    finally:
        conn.close()

    print(f"Upserted {len(products)} products. Table now has {total} rows.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--with-seeds", action="store_true", help="also load the curated staples in data/*.csv")
    parser.add_argument("--with-trader-joes", action="store_true", help="also load trader_joes_macros.json if present")
    args = parser.parse_args()
    setup(with_seeds=args.with_seeds, with_trader_joes=args.with_trader_joes)
