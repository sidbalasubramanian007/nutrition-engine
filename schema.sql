-- Final schema for the products table. Safe to run repeatedly (scripts/setup_db.py runs it on every setup).
CREATE TABLE IF NOT EXISTS products (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(255) NOT NULL UNIQUE,
    calories     NUMERIC NOT NULL,
    protein      NUMERIC NOT NULL,
    carbs        NUMERIC NOT NULL,
    fat          NUMERIC NOT NULL,
    fiber        NUMERIC NOT NULL DEFAULT 0,
    category     VARCHAR(50)  NOT NULL DEFAULT 'misc',
    max_servings INTEGER      NOT NULL DEFAULT 3,
    location     VARCHAR(100) NOT NULL DEFAULT 'Grocery',
    -- Meal slots the food belongs in (e.g. {breakfast,snack}); NULL until populated.
    meal_slots   TEXT[]
);

-- Bring tables created by the old migrate/seed scripts up to date: they lacked
-- meal_slots and (after import_csv.py recreated the table) the unique name constraint
-- that setup_db.py's upsert relies on.
ALTER TABLE products ADD COLUMN IF NOT EXISTS meal_slots TEXT[];
CREATE UNIQUE INDEX IF NOT EXISTS products_name_key ON products (name);
