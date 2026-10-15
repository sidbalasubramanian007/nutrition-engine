# Nutrition Engine (Macro-Tracker)

[![Tests](https://github.com/sidbalasubramanian007/nutrition-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/sidbalasubramanian007/nutrition-engine/actions/workflows/tests.yml)

A Streamlit app that builds a full daily meal plan from real food data (grocery staples, Trader Joe's products, and Chipotle/CAVA menu items) matched against user-defined macro targets (calories, protein, carbs, fat). Instead of pulling from a generic recipe database, it works off per-serving nutrition data and solves for the combination of real items that best hits your numbers.

## How it works

**Targets.** The sidebar includes a TDEE calculator (Mifflin-St Jeor equation) that turns age, weight, height, gender, activity level, and goal (maintenance/bulk/cut) into calorie, protein, fat, and carb targets. You can also override any of the four targets directly with the sliders.

**Optimizer.** The "Home Cooking Plan" tab builds the day's plan with `optimizer.py`, which solves it exactly as a mixed-integer linear program (MILP) using PuLP. The model is described in plain language below.

*Decision variables.* For every food, every meal it may go in, and every serving count from 1 up to its cap, there is a yes/no variable meaning "this food, in this meal, at this many servings". Servings and "is this food used in this meal" are sums of those variables. A food may go in a meal only if:
- the meal is in the food's `meal_slots`;
- its location matches the meal: Grocery, or the chosen restaurant for the restaurant meal when one is given;
- for breakfast, lunch and dinner, its category is `staple` or `lean_protein`. Snacks can be any category.

The serving cap is `min(max_servings, 3)` for main meals and 1 for snacks.

*Meal-structure constraints.* These mirror the heuristic in `solver.py`:
- breakfast, lunch and dinner each contain exactly one staple and one lean protein;
- the snack has one or two items;
- each food (by name) is used at most once per day, which also keeps dinner's staple different from lunch's;
- at most one serving count is chosen per food per meal.

*Fiber cap.* Total fiber must be at most 35g. This is a hard constraint; the heuristic only penalizes going over.

*Objective.* Minimize `20·|calories − target| + 100·|protein − target| + 20·|carbs − target| + 20·|fat − target|`, the same weights as the heuristic. Each absolute value is made linear with two nonnegative variables, over and under, where `total − target = over − under`. Minimizing `over + under` makes it equal the absolute deviation. Both are bounded by the lowest and highest totals the meal structure can actually reach. The reported `penalty` is computed with `solver.plan_penalty`, the heuristic's exact formula including its fiber term, so the two methods' scores are directly comparable.

*Solvers.*
- **HiGHS (default)** is used when `highspy` is installed, with presolve off.
- **CBC (fallback)**, bundled with PuLP 3.3.2, is used otherwise. It runs on all CPU cores.
- **Warm start (HiGHS only):** a seeded 2,000-iteration heuristic run supplies the starting plan. It doesn't print anything or change the caller's random state. CBC skips it, because it measured slightly slower with one.
- **Gap and status:** the relative gap tolerance defaults to 0.5%. Each result carries a status:
  - `optimal`: proven within the gap.
  - `feasible`: the time limit hit first; this is the best plan found so far.
  - `infeasible`: no plan satisfies the structure with the loaded foods.

*In the app.* The home tab calls the optimizer with `time_limit=1` and shows a status line under the macro breakdown:
- `optimal`: "Proven optimal · solved in X.XXs".
- `feasible`: "Best plan found in 1s (not yet proven optimal)".
- `infeasible`: an error suggesting you load more foods or widen your targets.

*Why proving optimality takes longer than finding the plan.* Solvers prove optimality with a lower bound from the problem's continuous relaxation, where servings may be fractional. With fractional servings the targets can usually be hit exactly, so that bound stays at 0 for most of the search. The solver then has to rule out every branch before the bound reaches the best penalty it found. In the benchmark below, the 1-second runs already returned the proven optimum for 53% of the targets proven optimal, but the median time to prove optimality was 2.0s. For the same reason, the 0.5% gap rarely ends a search early: measured against a bound near 0, the gap stays near 100% until the proof completes.

**Restaurant orders.** The Eating Out tab's "Hack My Menu" builds one Chipotle or CAVA order for the macros you have left, using `optimizer.optimize_restaurant_order` with `time_limit=1`. It shares the daily plan's model-building pieces: one-hot serving variables, the over/under objective, solver selection and status. Each restaurant item has a component type: `base`, `protein`, `beans`, `topping` or `sauce`. An order follows these rules:
- 1–2 bases and 1–2 proteins, each at 1–2 servings (capped by the item's `max_servings`);
- at most 1 beans;
- at most 4 toppings and sauces combined;
- every non-base, non-protein item at a single serving, and each item used at most once.

The objective has the same weights as the daily plan, but no fiber term or fiber cap. The reported `penalty` uses `solver.order_penalty`, the formula of the original restaurant heuristic. The app shows the same status line as the home tab. With one base per menu and a handful of items, orders are proven optimal in a few hundredths of a second.

*How it compares to the heuristic.* Under the same rules, the MILP matches or beats the heuristic. On the 16 test targets (8 per restaurant), it tied `run_restaurant_solver(rules=True)` every time and was never worse. That's expected: the menus are small enough that 50,000 random rule-following orders usually find the optimum too, and the MILP proves it. The original, unconstrained heuristic did report lower penalties on 12 of those 16 targets, but every one of those orders was invalid under the rules: double servings of a sauce or beans, no base, or no protein. Its lower scores came from orders the app no longer allows, not from better choices. `tests/test_optimizer.py` checks both things: every MILP order follows the rules, and the unconstrained heuristic only wins by breaking them.

**Heuristic baselines.** `solver.py` keeps the original randomized searches.
- `run_heuristic_solver()`: 50,000 iterations of building a random daily plan with the same meal structure, keeping the lowest-penalty one. It's the baseline in the benchmark.
- `run_restaurant_solver()`: random orders of 2–5 items at 1–2 servings each, ignoring component types. With `rules=True` it samples only orders that follow the same structure rules as the MILP. The rules are defined once in `solver.py` (`ORDER_COMPONENT_LIMITS` and friends) and used by both.

Their tests remain. The app still uses `solver.load_food_data()` to load foods.

**Data.**
- `food_data.csv` is the main dataset: grocery staples plus Chipotle and CAVA items, each tagged with a `location`.
- Curated staples (chicken, salmon, oats, rice, etc.) live in `data/seed_*.csv`.
- `scraper.py` uses Playwright to load a Trader Joe's category page and BeautifulSoup to pull product names. It then uses the Gemini API (`google-genai`) to estimate per-serving macros (calories/protein/carbs/fat/fiber) for each item, and saves the result to `trader_joes_macros.json`.

Every CSV has a `Meal_Slots` column listing the meals a food may appear in, separated by `|` (e.g. `breakfast|snack`); valid slots are `breakfast`, `lunch`, `dinner` and `snack`. Adding a food is a data change only. If `Meal_Slots` is blank, or for Trader Joe's items (which have none), a default applies: restaurant items and `lean_protein` foods go to `lunch|dinner`, and everything else to all four slots. `scripts/setup_db.py` loads `food_data.csv` by default and the other two sources on request.

Every CSV also has a `Component_Type` column. Each restaurant item needs one of `base`, `protein`, `beans`, `topping` or `sauce`, and `setup_db.py` rejects a missing or unknown value. Grocery items leave it blank.

**Database.** Food data lives in PostgreSQL, in a single `products` table defined in `schema.sql`, with columns for name, calories, protein, carbs, fat, fiber, category, max_servings, location, meal_slots, component_type and source. `source` records where a food's macros came from: `manual` (`food_data.csv` and the seed files), `gemini_estimate` (the Trader Joe's items, whose macros are LLM estimates) or `usda` (verified against USDA FoodData Central). The sidebar's **Exclude estimated foods** checkbox leaves `gemini_estimate` foods out of the pool before optimizing. The app checks the connection at startup and reads this table each time a plan is generated.

## Benchmark

`scripts/benchmark_solvers.py` compares three methods on the same 50 targets:

| Method | Median penalty | Mean penalty | Median abs. error: kcal | protein (g) | carbs (g) | fat (g) | Median time |
|---|---|---|---|---|---|---|---|
| Heuristic (50,000 iterations) | 388.0 | 1321.9 | 6.0 | 1.0 | 4.5 | 3.5 | 0.95s |
| MILP, `time_limit=1` (the app's setting) | 84.0 | 367.0 | 2.0 | 0.0 | 1.0 | 1.3 | 1.04s |
| MILP, `time_limit=30`, `gap_rel=0` | 50.0 | 346.8 | 2.0 | 0.0 | 0.0 | 0.7 | 2.98s |

- MILP@1s scored at or below the heuristic on **100%** of targets.
- **94%** of targets (47 of 50) were proven optimal within 30s, with a median of **2.0s** to prove.
- MILP@1s already matched the proven optimum on 53% of those 47 targets. At 1s, 18 runs were proven optimal and 32 returned the best plan found so far.
- The 1-second runs take slightly over 1s in total, because building the model and the warm start come on top of the solver's time limit.
- The largest penalties come from high-calorie, low-protein targets. The four targets whose best possible penalty is over 1,000 are all 3,188–3,513 kcal with only 95–134g protein. No plan gets close to them, because main-meal servings cap at 3 and the snack at two single servings. These targets pull every method's mean far above its median.

**Method.**
- **Food pool:** the 39 grocery foods from `food_data.csv`, `data/seed_*.csv` and `trader_joes_macros.json`, merged with `setup_db.py`'s rules and read from the files directly (no database).
- **Targets:** 50, generated with seed 2026:
  - calories uniform in 1,600–3,600;
  - protein 0.7–1.2 g per lb for a random 120–220 lb person;
  - fat 20–35% of calories;
  - the remaining calories as carbs;
  - targets that would leave under 50g of carbs are redrawn.
- **Heuristic:** seeded per target.
- **Time to prove:** measured with the `time_limit=30`, `gap_rel=0` run.
- **Run conditions:** these results come from the data as of commit `35c3a43`, on an 8-core Apple Silicon Mac with nothing else running. Timings will vary by machine.

**Rerun it** from the repo root:

```bash
timeout 1800 python scripts/benchmark_solvers.py
# macOS has no `timeout`; this is equivalent:
perl -e 'alarm shift; exec @ARGV' 1800 python scripts/benchmark_solvers.py
```

It prints one progress line per target and then the summary. Results are written to `benchmark_results.json` (gitignored), which is rewritten after every target, so a timeout keeps the targets finished so far.

## Tech stack

- **Python 3.12** (the version CI tests against)
- **Streamlit**: UI (`app.py`)
- **PuLP 3.3.2**: MILP modeling (`optimizer.py`); its bundled CBC solver is the fallback
- **HiGHS** (`highspy`): the default MILP solver
- **PostgreSQL** + **psycopg2**: food data storage (local Postgres via Docker Compose)
- **Playwright** + **BeautifulSoup4**: scraping Trader Joe's product listings (`scraper.py`)
- **google-genai** (Gemini API): LLM-based macro estimation for scraped items
- **python-dotenv**: loads database settings and `GEMINI_API_KEY` from a local `.env` file
- **pytest**: tests (`tests/`)

See `requirements.txt` and `requirements-dev.txt` for pinned versions.

## Project structure

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI. Has the TDEE calculator sidebar and macro target sliders. The "Home Cooking Plan" tab runs `optimizer.optimize_meal_plan` (1s limit) and shows the meal plan, macro breakdown and solver status. The "Eating Out Plan" tab has the restaurant order calculator and the "Hack My Menu" auto-builder, which runs `optimizer.optimize_restaurant_order` (1s limit). |
| `optimizer.py` | The MILP optimizers. `optimize_meal_plan` covers the daily plan: eligible food/meal placements, meal-structure and fiber constraints, heuristic warm start. `optimize_restaurant_order` covers a single restaurant order with component-type rules. Both share one-hot serving variables, the linearized weighted-deviation objective and HiGHS/CBC selection. |
| `solver.py` | The heuristic meal-plan and restaurant-order searches, kept as baselines. Also provides `load_food_data()` (used by the app), the `plan_penalty()` and `order_penalty()` formulas, and the restaurant order rules, all shared with `optimizer.py`. |
| `calculator.py` | TDEE (Mifflin-St Jeor) and macro-target math: BMR → TDEE by activity level → goal adjustment, protein estimate by bodyweight/goal, and fat/carb split from remaining calories. |
| `scraper.py` | Scrapes a Trader Joe's category page with Playwright/BeautifulSoup, then calls the Gemini API to estimate nutrition macros for each item and writes `trader_joes_macros.json`. |
| `db.py` | Shared `get_connection()` helper. Opens the Postgres connection from `DATABASE_URL` if set, otherwise from `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` (with local defaults). Used by `app.py`, `solver.py`, `scripts/setup_db.py` and `scripts/check_db.py`. |
| `schema.sql` | Final `products` table schema. Idempotent; also upgrades tables created by the old migration scripts. |
| `docker-compose.yml` | Local `postgres:16` on host port 5433, configured from the same `DB_*` variables as `db.py`. |
| `food_data.csv` | Main food dataset (grocery + restaurant items, with restaurant component types), loaded by default. |
| `data/seed_*.csv` | Curated staple proteins and carbs (same columns as `food_data.csv`), loaded with `--with-seeds`. |
| `data/usda_overrides.csv` | USDA-verified macros accepted in `scripts/usda_lookup.py` (created on first accept), applied last by `setup_db.py`. |
| `trader_joes_macros.json` | Scraper output (Trader Joe's items), loaded with `--with-trader-joes`. |
| `scripts/setup_db.py` | One-step database setup: applies `schema.sql`, then upserts the food data by name, so it's safe to re-run. |
| `scripts/check_db.py` | Prints all products in the database, sorted by protein, descending. |
| `scripts/usda_lookup.py` | Compares grocery foods with USDA FoodData Central and saves accepted values to `data/usda_overrides.csv`. |
| `scripts/audit_data.py` | Prints products whose labelled calories differ from 4P + 4C + 9F by more than 20% (the `nutrition_audit` view). |
| `scripts/benchmark_solvers.py` | Heuristic vs. MILP benchmark (see [Benchmark](#benchmark)). Reads the data files directly, with no database needed. |
| `tests/` | pytest suite for the calculator, `db.py`, `setup_db.py`, the heuristic solver and the optimizer. `conftest.py` puts `scripts/` on the import path. |

`app.py`, `optimizer.py`, `solver.py`, `calculator.py`, `scraper.py` and `db.py` are the application modules at the repo root. The scripts in `scripts/` are run by hand, from the repo root, and each adds the repo root to `sys.path` so it can import those modules.

## Setup

### 1. Virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # optional: pytest, to run the tests
```

### 2. Environment variables

`db.py`'s `get_connection()` is the only place that opens database connections, and it reads its settings from the environment (via `python-dotenv`):

- If `DATABASE_URL` is set and non-empty (e.g. `postgresql://user:password@host:5432/nutrition_db` for hosted Postgres), it is used as-is and the `DB_*` variables are ignored.
- Otherwise it uses the individual variables, falling back to local defaults:

| Variable | Default |
|---|---|
| `DB_HOST` | `localhost` |
| `DB_PORT` | `5432` |
| `DB_NAME` | `nutrition_db` |
| `DB_USER` | unset (libpq uses your OS username) |
| `DB_PASSWORD` | empty |

Copy `.env.example` to `.env` in the repo root and fill it in. `GEMINI_API_KEY` is only needed to run `scraper.py`.

### 3. Database

**Option A: Docker Compose (recommended).** `docker-compose.yml` runs `postgres:16` and creates the user, password and database from your `.env`. It maps to host port **5433**, so it won't clash with a Postgres already installed on 5432. Set these in `.env`:

```
DB_HOST=localhost
DB_PORT=5433
DB_NAME=nutrition_db
DB_USER=nutrition
DB_PASSWORD=choose-a-password
```

`DB_USER` and `DB_PASSWORD` are required here. Compose refuses to start without them, so the container and `db.py` always agree on credentials. Then start the database:

```bash
docker compose up -d --wait
```

**Option B: an existing local Postgres.** Keep `DB_PORT=5432` (or leave it unset) and create the database:

```bash
createdb nutrition_db
```

### 4. Load the data

With the venv active, from the repo root:

```bash
python scripts/setup_db.py
```

This creates the `products` table from `schema.sql` if needed, then upserts every row of `food_data.csv` by name. It is safe to re-run at any time: rows are updated in place, never duplicated. To load the full food pool used in the benchmark, add both optional sources:

```bash
python scripts/setup_db.py --with-seeds --with-trader-joes
```

- `--with-seeds` adds the curated staples in `data/seed_*.csv`.
- `--with-trader-joes` adds `trader_joes_macros.json`, if it's present.

If the same name appears in more than one source, `food_data.csv` wins over `data/seed_*.csv`, which wins over the Trader Joe's data. USDA-verified values from `data/usda_overrides.csv` are applied after that, on every run (see below). Re-running without a flag doesn't remove rows a previous flagged run added. To get back to the default set, recreate the database (with Docker: `docker compose down -v && docker compose up -d --wait`) and run the script again.

To refresh the Trader Joe's data first, run `python scraper.py` (requires `GEMINI_API_KEY`).

**Verify macros against USDA (optional).** `scripts/usda_lookup.py` compares each grocery food with USDA FoodData Central. It needs `USDA_API_KEY` in `.env` ([free key](https://fdc.nal.usda.gov/api-key-signup)).

```bash
python scripts/usda_lookup.py --dry-run                 # show comparisons only
python scripts/usda_lookup.py --only "Rolled Oats"      # review one food
python scripts/usda_lookup.py                           # review every grocery food
python scripts/setup_db.py --with-seeds --with-trader-joes   # then load accepted values
```

How the lookup works:
- **Which database it searches.** Generic foods are searched in Foundation and SR Legacy, which report nutrients per 100 g. You're asked for the gram weight of one serving; the default is USDA's first listed portion, if it has one. Trader Joe's items are searched in USDA's Branded data, which reports per labelled serving, and every word of the name must match. As of writing, none of the Trader Joe's items has a match.
- **Reviewing candidates.** Each food shows our values next to the USDA candidate's, scaled to one serving. Answer `y` to accept, `n` to skip, a number to view another of the top 5, or `q` to quit. USDA's ranking isn't always right (for "Chicken Breast" the first complete match is breaded tenders), so check the description before accepting.
- **What gets saved.** Accepted foods are appended to `data/usda_overrides.csv` and skipped on later runs. Restaurant items aren't looked up.
- **What `setup_db.py` does with them.** It replaces only those foods' calories, protein, carbs, fat and fiber, and sets `source='usda'`; category, meal slots and everything else stay.

You can sanity-check the loaded data with:

```bash
python scripts/check_db.py
```

## Running the app

```bash
streamlit run app.py
```

## Running the tests

```bash
pytest
```
