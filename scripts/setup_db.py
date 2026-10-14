"""Creates the products schema and loads the food data. Safe to re-run.

Usage (from the repo root):
    python scripts/setup_db.py                     # food_data.csv only
    python scripts/setup_db.py --with-seeds        # + curated staples in data/*.csv
    python scripts/setup_db.py --with-trader-joes  # + trader_joes_macros.json (scraper output)

Rows are upserted by name. When the same name appears in more than one source,
food_data.csv wins over the seed files, which win over the Trader Joe's data.
"""
import argparse
import csv
import glob
import json
import os
import sys

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

UPSERT_QUERY = """
INSERT INTO products (name, calories, protein, carbs, fat, fiber, category, max_servings, location)
VALUES (%(name)s, %(calories)s, %(protein)s, %(carbs)s, %(fat)s, %(fiber)s, %(category)s, %(max_servings)s, %(location)s)
ON CONFLICT (name) DO UPDATE SET
    calories     = EXCLUDED.calories,
    protein      = EXCLUDED.protein,
    carbs        = EXCLUDED.carbs,
    fat          = EXCLUDED.fat,
    fiber        = EXCLUDED.fiber,
    category     = EXCLUDED.category,
    max_servings = EXCLUDED.max_servings,
    location     = EXCLUDED.location;
"""


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
    """Reads scraper output into product dicts, tagging category by keyword."""
    with open(path) as f:
        items = json.load(f)
    return [
        {
            "name": item["name"],
            "calories": item["calories"],
            "protein": item["protein"],
            "carbs": item["carbs"],
            "fat": item["fat"],
            "fiber": item["fiber"],
            "category": tag_category(item["name"]),
            "max_servings": 3,
            "location": "Grocery",
        }
        for item in items
    ]


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


def setup(with_seeds=False, with_trader_joes=False):
    products = collect_products(with_seeds, with_trader_joes)

    conn = db.get_connection()
    try:
        with conn, conn.cursor() as cur:
            with open(SCHEMA_PATH) as f:
                cur.execute(f.read())
            cur.executemany(UPSERT_QUERY, products)
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
