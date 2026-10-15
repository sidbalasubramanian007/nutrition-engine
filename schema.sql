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
    meal_slots   TEXT[],
    -- Restaurant order component (base, protein, beans, topping, sauce); NULL for grocery items.
    component_type VARCHAR(20)
);

-- Bring older tables up to date: tables from the old migrate/seed scripts lacked meal_slots
-- and (after import_csv.py recreated the table) the unique name constraint that setup_db.py's
-- upsert relies on; tables set up before restaurant orders lack component_type.
ALTER TABLE products ADD COLUMN IF NOT EXISTS meal_slots TEXT[];
ALTER TABLE products ADD COLUMN IF NOT EXISTS component_type VARCHAR(20);
CREATE UNIQUE INDEX IF NOT EXISTS products_name_key ON products (name);

-- Data checks, so bad values can't enter the table. Postgres has no ADD CONSTRAINT IF NOT
-- EXISTS, so each is dropped and re-added: idempotent, and an edited definition takes effect
-- on the next setup_db.py run. NOT VALID enforces them on every insert and update straight
-- away but skips checking existing rows, so a re-run can first upsert corrected data; then
-- setup_db.py validates every constraint against all rows in the same transaction.
-- (NULL meal_slots still pass; setup_db.py backfills them in the same transaction.)
ALTER TABLE products
    DROP CONSTRAINT IF EXISTS products_calories_nonnegative,
    ADD CONSTRAINT products_calories_nonnegative CHECK (calories >= 0) NOT VALID,
    DROP CONSTRAINT IF EXISTS products_protein_nonnegative,
    ADD CONSTRAINT products_protein_nonnegative CHECK (protein >= 0) NOT VALID,
    DROP CONSTRAINT IF EXISTS products_carbs_nonnegative,
    ADD CONSTRAINT products_carbs_nonnegative CHECK (carbs >= 0) NOT VALID,
    DROP CONSTRAINT IF EXISTS products_fat_nonnegative,
    ADD CONSTRAINT products_fat_nonnegative CHECK (fat >= 0) NOT VALID,
    DROP CONSTRAINT IF EXISTS products_fiber_nonnegative,
    ADD CONSTRAINT products_fiber_nonnegative CHECK (fiber >= 0) NOT VALID,
    DROP CONSTRAINT IF EXISTS products_max_servings_range,
    ADD CONSTRAINT products_max_servings_range CHECK (max_servings BETWEEN 1 AND 5) NOT VALID,
    DROP CONSTRAINT IF EXISTS products_category_known,
    ADD CONSTRAINT products_category_known
        CHECK (category IN ('lean_protein', 'staple', 'carb', 'fat', 'bakery', 'misc')) NOT VALID,
    DROP CONSTRAINT IF EXISTS products_meal_slots_valid,
    ADD CONSTRAINT products_meal_slots_valid
        CHECK (cardinality(meal_slots) > 0
               AND meal_slots <@ ARRAY['breakfast', 'lunch', 'dinner', 'snack']::TEXT[]) NOT VALID;
