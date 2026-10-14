# Nutrition Engine (Macro-Tracker)

[![Tests](https://github.com/sidbalasubramanian007/nutrition-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/sidbalasubramanian007/nutrition-engine/actions/workflows/tests.yml)

A Streamlit app that builds a full daily meal plan from real grocery product data — currently Trader Joe's items — matched against strict, user-defined macro targets (calories, protein, carbs, fat). Instead of pulling from a generic recipe database, it works off actual product nutrition data and searches for the combination of real items that best hits your numbers.

## How it works

**Targets.** The sidebar includes a TDEE calculator (Mifflin-St Jeor equation) that turns age, weight, height, gender, activity level, and goal (maintenance/bulk/cut) into calorie, protein, fat, and carb targets. You can also override any of the four targets directly with the sliders.

**Solver.** `solver.py` is a heuristic search, not a linear/integer solver. For each of 50,000 iterations it:
1. Builds a structured daily plan — breakfast (carb + protein), lunch (protein + carb), dinner (protein + a different carb than lunch), and a snack (up to 2 single-serving items) — using a `MEAL_SLOT_MAP` that restricts which foods can appear in which meal (so, e.g., steak doesn't end up at breakfast).
2. Randomly assigns 1–3 servings to each item (snacks capped at 1 serving), keeping every food unique within the day.
3. Scores the plan with a **weighted penalty across all four macros** (calories, protein, carbs, fat), plus an extra penalty if fiber exceeds 35g. This is deliberate: a naive solver can "cheat" by maxing out a single macro at the expense of the others, so every target is penalized simultaneously and the lowest-penalty plan across all iterations wins.

**Data.** `scraper.py` uses Playwright to load a Trader Joe's category page, BeautifulSoup to pull product names, and the Gemini API (`google-genai`) to estimate per-serving macros (calories/protein/carbs/fat/fiber) for each scraped item, saving the result to `trader_joes_macros.json`. The main dataset is `food_data.csv` (grocery staples plus Chipotle and CAVA items, each tagged with a `location`). Curated staples (chicken, salmon, oats, rice, etc.) live in `data/*.csv`. `scripts/setup_db.py` loads `food_data.csv` by default and the other two sources on request.

**Database.** Food data lives in a local PostgreSQL `nutrition_db`, in a single `products` table defined in `schema.sql` (name, calories, protein, carbs, fat, fiber, category, max_servings, location, meal_slots). The app queries this table on every "Generate Optimal Plan" click.

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
| `db.py` | Shared `get_connection()` helper — opens the Postgres connection from `DATABASE_URL` if set, otherwise from `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` (with local defaults). Used by `app.py`, `solver.py` and every script below. |
| `schema.sql` | Final `products` table schema. Idempotent; also upgrades tables created by the old migration scripts. |
| `food_data.csv` | Main food dataset (grocery + restaurant items), loaded by default. |
| `data/*.csv` | Curated staple proteins and carbs (same columns as `food_data.csv`), loaded with `--with-seeds`. |
| `scripts/setup_db.py` | One-step database setup: applies `schema.sql`, then upserts the food data by name, so it's safe to re-run. |
| `docker-compose.yml` | Local `postgres:16` on host port 5433, configured from the same `DB_*` variables as `db.py`. |
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

Create a `.env` file in the repo root (see `.env.example`):

```
GEMINI_API_KEY=your-gemini-api-key-here
DB_HOST=localhost
DB_PORT=5432
DB_NAME=nutrition_db
DB_USER=
DB_PASSWORD=
```

`GEMINI_API_KEY` is only required to run `scraper.py`. The database variables can be omitted entirely for a default local Postgres install — the defaults just work.

### 3. Database setup

You need a Postgres database to load into. Pick one of the two options below.

**Option A: Docker (recommended).** `docker-compose.yml` runs `postgres:16` and creates the user, password and database from your `.env`. It maps to host port **5433** so it won't clash with a Postgres already installed on 5432. Set these in `.env`:

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

**Load the data.** With the venv active, from the repo root:

```bash
python scripts/setup_db.py
```

This creates the `products` table from `schema.sql` if needed, then upserts every row of `food_data.csv` by name. It is safe to re-run at any time: rows are updated in place, never duplicated. Optional extras:

```bash
python scripts/setup_db.py --with-seeds        # + curated staples in data/*.csv
python scripts/setup_db.py --with-trader-joes  # + trader_joes_macros.json, if present
```

If the same name appears in more than one source, `food_data.csv` wins over `data/*.csv`, which wins over the Trader Joe's data. Re-running without a flag doesn't remove rows a previous flagged run added. To get back to the default set, recreate the database (with Docker: `docker compose down -v && docker compose up -d --wait`) and run the script again.

To refresh the Trader Joe's data first, run `python scraper.py` (requires `GEMINI_API_KEY`).

You can sanity-check the loaded data with:

```bash
python scripts/check_db.py
```

## Running the app

```bash
streamlit run app.py
```
