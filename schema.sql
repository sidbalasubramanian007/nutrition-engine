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
    component_type VARCHAR(20),
    -- Where the macros came from: 'manual', 'usda' (verified) or 'gemini_estimate' (LLM estimate)
    source       VARCHAR(20)  NOT NULL DEFAULT 'manual',
    -- Official page the values were read from (restaurant items fetched by scripts/fetch_restaurant_menus.py)
    source_url   TEXT
);

-- Bring older tables up to date: tables from the old migrate/seed scripts lacked meal_slots
-- and (after import_csv.py recreated the table) the unique name constraint that setup_db.py's
-- upsert relies on; tables set up before restaurant orders lack component_type, and ones
-- set up before USDA data lack source, and ones set up before official menus lack source_url.
ALTER TABLE products ADD COLUMN IF NOT EXISTS meal_slots TEXT[];
ALTER TABLE products ADD COLUMN IF NOT EXISTS component_type VARCHAR(20);
ALTER TABLE products ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'manual';
ALTER TABLE products ADD COLUMN IF NOT EXISTS source_url TEXT;
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
    DROP CONSTRAINT IF EXISTS products_source_known,
    ADD CONSTRAINT products_source_known
        CHECK (source IN ('manual', 'usda', 'gemini_estimate')) NOT VALID,
    DROP CONSTRAINT IF EXISTS products_meal_slots_valid,
    ADD CONSTRAINT products_meal_slots_valid
        CHECK (cardinality(meal_slots) > 0
               AND meal_slots <@ ARRAY['breakfast', 'lunch', 'dinner', 'snack']::TEXT[]) NOT VALID;

-- Sanity check of labelled calories against the macros, using the general Atwater factors
-- (4 kcal/g protein, 4 kcal/g carbs, 9 kcal/g fat). kcal_difference is labelled minus Atwater;
-- percent_error is relative to the labelled calories. flagged marks errors above 20% (or any
-- macro calories on a 0-calorie label). scripts/audit_data.py prints the flagged rows.
CREATE OR REPLACE VIEW nutrition_audit AS
SELECT
    name,
    location,
    category,
    calories,
    protein,
    carbs,
    fat,
    4 * protein + 4 * carbs + 9 * fat AS atwater_kcal,
    calories - (4 * protein + 4 * carbs + 9 * fat) AS kcal_difference,
    ROUND(100 * ABS(calories - (4 * protein + 4 * carbs + 9 * fat)) / NULLIF(calories, 0), 1) AS percent_error,
    CASE
        WHEN calories = 0 THEN 4 * protein + 4 * carbs + 9 * fat > 0
        ELSE ABS(calories - (4 * protein + 4 * carbs + 9 * fat)) > 0.20 * calories
    END AS flagged
FROM products;

-- Saved meal plans (see db.save_plan). A plan's achieved macros aren't stored: list_plans and
-- get_plan compute them from plan_items and the products' current macros.
CREATE TABLE IF NOT EXISTS plans (
    id              SERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    target_calories NUMERIC      NOT NULL,
    target_protein  NUMERIC      NOT NULL,
    target_carbs    NUMERIC      NOT NULL,
    target_fat      NUMERIC      NOT NULL,
    penalty         NUMERIC      NOT NULL,
    -- Infeasible results have no items, so only these can be saved
    status          VARCHAR(20)  NOT NULL CHECK (status IN ('optimal', 'feasible')),
    solver          VARCHAR(20)  NOT NULL
);

CREATE TABLE IF NOT EXISTS plan_items (
    id         SERIAL PRIMARY KEY,  -- insertion order = display order
    plan_id    INTEGER     NOT NULL REFERENCES plans (id) ON DELETE CASCADE,
    -- No cascade: a product used by a saved plan can't be deleted out from under it
    product_id INTEGER     NOT NULL REFERENCES products (id),
    meal       VARCHAR(20) NOT NULL CHECK (meal IN ('Breakfast', 'Lunch', 'Dinner', 'Snack')),
    servings   INTEGER     NOT NULL CHECK (servings >= 1)
);
CREATE INDEX IF NOT EXISTS plan_items_plan_id_idx ON plan_items (plan_id);
