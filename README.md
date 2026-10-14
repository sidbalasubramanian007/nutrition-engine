# Nutrition Engine (Macro-Tracker)

[![Tests](https://github.com/sidbalasubramanian007/nutrition-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/sidbalasubramanian007/nutrition-engine/actions/workflows/tests.yml)

A Streamlit app that builds a full daily meal plan from real grocery product data — currently Trader Joe's items — matched against strict, user-defined macro targets (calories, protein, carbs, fat). Instead of pulling from a generic recipe database, it works off actual product nutrition data and searches for the combination of real items that best hits your numbers.

## How it works

**Targets.** The sidebar includes a TDEE calculator (Mifflin-St Jeor equation) that turns age, weight, height, gender, activity level, and goal (maintenance/bulk/cut) into calorie, protein, fat, and carb targets. You can also override any of the four targets directly with the sliders.

**Solver.** `solver.py` is a heuristic search, not a linear/integer solver. For each of 50,000 iterations it:
1. Builds a structured daily plan — breakfast (carb + protein), lunch (protein + carb), dinner (protein + a different carb than lunch), and a snack (up to 2 single-serving items) — using a `MEAL_SLOT_MAP` that restricts which foods can appear in which meal (so, e.g., steak doesn't end up at breakfast).
2. Randomly assigns 1–3 servings to each item (snacks capped at 1 serving), keeping every food unique within the day.
3. Scores the plan with a **weighted penalty across all four macros** (calories, protein, carbs, fat), plus an extra penalty if fiber exceeds 35g. This is deliberate: a naive solver can "cheat" by maxing out a single macro at the expense of the others, so every target is penalized simultaneously and the lowest-penalty plan across all iterations wins.

**Data.** `scraper.py` uses Playwright to load a Trader Joe's category page, BeautifulSoup to pull product names, and the Gemini API (`google-genai`) to estimate per-serving macros (calories/protein/carbs/fat/fiber) for each scraped item, saving the result to `trader_joes_macros.json`. That file is then loaded into Postgres. A set of `seed_*.py` scripts also hand-seed additional curated staples (chicken, salmon, oats, rice, etc.) directly, independent of the scraper, so the solver always has reliable building blocks for each meal slot.

**Database.** Food data lives in a local PostgreSQL `nutrition_db`, in a single `products` table (name, calories, protein, carbs, fat, fiber, category, max_servings). The app queries this table on every "Generate Optimal Plan" click.

## Tech stack

- **Python 3**
- **Streamlit** — UI (`app.py`)
- **PostgreSQL** + **psycopg2** — product data storage
- **Playwright** + **BeautifulSoup4** — scraping Trader Joe's product listings (`scraper.py`)
- **google-genai** (Gemini API) — LLM-based macro estimation for scraped items
- **python-dotenv** — loads `GEMINI_API_KEY` from a local `.env` file

See `requirements.txt` for pinned versions.

## Project structure

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI: TDEE calculator sidebar, macro target sliders, and the "Generate Optimal Plan" button that runs the solver and renders the meal plan + macro breakdown. |
| `calculator.py` | TDEE (Mifflin-St Jeor) and macro-target math: BMR → TDEE by activity level → goal adjustment, protein estimate by bodyweight/goal, and fat/carb split from remaining calories. |
| `solver.py` | The heuristic meal-plan solver: `MEAL_SLOT_MAP`, structured plan construction, serving-size selection, four-macro penalty scoring, and the iteration loop that picks the best plan. |
| `scraper.py` | Scrapes a Trader Joe's category page with Playwright/BeautifulSoup, then calls the Gemini API to estimate nutrition macros for each item and writes `trader_joes_macros.json`. |
| `db.py` | Shared `get_connection()` helper — opens the Postgres connection using `DB_NAME`/`DB_HOST` env vars (with local defaults), used by every script below and by `solver.py`. |
| `scripts/migrate.py` | Creates the `products` table (if it doesn't exist) and loads `trader_joes_macros.json` into it. |
| `scripts/tag_data.py` | Adds a `category` column and tags existing rows (`bakery`, `lean_protein`, or default `misc`) based on keyword matches in the product name. |
| `scripts/migrate_limits.py` | Adds a `max_servings` column (default 3) and backfills existing rows. |
| `scripts/seed_protein.py`, `scripts/seed_carbs.py`, `scripts/seed_meat.py`, `scripts/seed_elite.py` | Hand-seed curated staple items (proteins, carb staples, additional lean proteins/sides) directly into `products`, independent of the scraper. |
| `scripts/check_db.py` | Utility script — prints all products in the DB sorted by protein, descending. |

`app.py`, `calculator.py`, `solver.py`, `scraper.py`, and `db.py` are the core application modules and stay at the repo root. Everything in `scripts/` is a one-off migration/seed/inspection script, run manually during setup — each adjusts `sys.path` to import `db` from the parent directory.

## Setup

### 1. Virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment variables

`db.py`'s `get_connection()` reads `DB_NAME`/`DB_HOST` from the environment (via `python-dotenv`), falling back to `nutrition_db`/`localhost` if unset — so a `.env` file is only needed to point at a non-local database, or to supply the Gemini key.

Create a `.env` file in the repo root (see `.env.example`):

```
GEMINI_API_KEY=your-gemini-api-key-here
DB_HOST=localhost
DB_NAME=nutrition_db
```

`GEMINI_API_KEY` is only required to run `scraper.py`. `DB_HOST`/`DB_NAME` can be omitted entirely for local development — the defaults just work.

### 3. Database setup

Requires a local PostgreSQL instance.

```bash
createdb nutrition_db
```

Then, with the venv active and from the repo root, run the migration and seed scripts **in this order**:

```bash
# (Optional) scrape fresh product data — requires GEMINI_API_KEY
python scraper.py

# Create the products table and load scraper output (if trader_joes_macros.json exists)
python scripts/migrate.py

# Add curated meat items (no category/max_servings yet)
python scripts/seed_meat.py

# Add category column and tag all rows (bakery / lean_protein / misc)
python scripts/tag_data.py

# Add max_servings column and backfill defaults
python scripts/migrate_limits.py

# Add remaining curated staples with explicit category + max_servings
python scripts/seed_protein.py
python scripts/seed_carbs.py
python scripts/seed_elite.py
```

You can sanity-check the loaded data at any point with:

```bash
python scripts/check_db.py
```

## Running the app

```bash
streamlit run app.py
```
