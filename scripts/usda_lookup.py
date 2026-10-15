"""Checks grocery foods against USDA FoodData Central and records verified macros.

Usage (from the repo root; needs USDA_API_KEY in .env, free from https://fdc.nal.usda.gov/api-key-signup):
    python scripts/usda_lookup.py                      # review every grocery food interactively
    python scripts/usda_lookup.py --only "Rolled Oats" # just one food
    python scripts/usda_lookup.py --dry-run            # show comparisons, ask nothing, write nothing

For each grocery food (restaurant items are skipped; USDA doesn't cover them) it searches FDC:
Trader Joe's items in the Branded data as "Trader Joe's <name>" with every word required (a
looser search only surfaces other products, e.g. another brand's muffins), everything else in
Foundation and SR Legacy. Branded foods report nutrients per labelled serving, which is used as-is.
Foundation/SR Legacy report per 100 g, so you're asked for the gram weight of one serving
(defaulting to the food's first USDA portion, if any) and values are scaled to it.

Each food shows our values next to the USDA candidate's. Answer y to accept, n to skip, a number
to look at another of the top 5 candidates, or q to stop. Accepted foods are appended to
data/usda_overrides.csv, which scripts/setup_db.py applies on its next run; foods already in that
file are skipped on re-runs. --dry-run never prompts: per-100 g foods use the default serving.
"""
import argparse
import csv
import os
import sys
import time

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import setup_db

API_BASE = "https://api.nal.usda.gov/fdc/v1"
CANDIDATES = 5
PER_100G_TYPES = ("Foundation", "SR Legacy")
MACROS = ["calories", "protein", "carbs", "fat", "fiber"]
OVERRIDE_FIELDS = ["Name", "Calories", "Protein", "Carbs", "Fat", "Fiber", "Fdc_Id", "Serving_Grams"]

# FDC nutrient numbers, in order of preference. Foundation foods often report energy only as
# Atwater general (957) or specific (958) factors instead of 208 (268 is energy in kJ, never
# used), and fiber as total dietary fiber by AOAC 2011.25 (293) instead of 291.
NUTRIENT_NUMBERS = {
    "calories": ["208", "957", "958"],
    "protein": ["203"],
    "carbs": ["205", "205.2"],
    "fat": ["204"],
    "fiber": ["291", "293"],
}
# Branded labelNutrients keys (values are per labelled serving)
LABEL_KEYS = {"calories": "calories", "protein": "protein", "carbs": "carbohydrates", "fat": "fat", "fiber": "fiber"}
GRAM_UNITS = {"g", "grm", "gram", "grams"}

RETRY_STATUSES = {429, 500, 502, 503, 504}


class FdcError(Exception):
    pass


class FdcClient:
    """Minimal FDC API client. The key travels only in the X-Api-Key header, never in a URL."""

    def __init__(self, api_key, session=None, sleep=time.sleep, max_retries=5, timeout=30):
        self._api_key = api_key
        self.session = session or requests.Session()
        self.session.headers["X-Api-Key"] = api_key
        self.sleep = sleep
        self.max_retries = max_retries
        self.timeout = timeout

    def _scrub(self, text):
        return str(text).replace(self._api_key, "***") if self._api_key else str(text)

    def post(self, path, payload):
        """POSTs JSON, retrying rate limits (429, honoring Retry-After), server errors and network errors."""
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(f"{API_BASE}{path}", json=payload, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise FdcError(f"FDC request failed: {self._scrub(e)}") from None
                self.sleep(min(2 ** attempt, 60))
                continue
            if response.status_code in RETRY_STATUSES and attempt < self.max_retries:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 60)
                if response.status_code == 429:
                    print(f"  rate limited by FDC, waiting {wait:g}s...")
                self.sleep(wait)
                continue
            if response.status_code != 200:
                hint = " (check USDA_API_KEY)" if response.status_code in (401, 403) else ""
                raise FdcError(f"FDC returned HTTP {response.status_code} for {path}{hint}: "
                               f"{self._scrub(response.text[:200])}")
            return response.json()
        raise FdcError(f"FDC request to {path} kept failing after {self.max_retries} retries")

    def search(self, query, data_types, require_all_words=False):
        payload = {"query": query, "dataType": list(data_types), "pageSize": CANDIDATES}
        if require_all_words:
            payload["requireAllWords"] = True
        return self.post("/foods/search", payload).get("foods", [])[:CANDIDATES]

    def details(self, fdc_ids):
        """{fdcId: full food details} for up to 20 ids in one request."""
        foods = self.post("/foods", {"fdcIds": list(fdc_ids), "format": "full"})
        return {food["fdcId"]: food for food in foods}


# --- parsing and scaling (no network) ---

def nutrient_amount(food, numbers):
    """First available amount for the given nutrient numbers, from full or abridged FDC formats."""
    found = {}
    for entry in food.get("foodNutrients", []):
        nutrient = entry.get("nutrient") or {}
        number = str(nutrient.get("number") or entry.get("nutrientNumber") or "")
        amount = entry.get("amount", entry.get("value"))
        if number and amount is not None:
            found.setdefault(number, float(amount))
    for number in numbers:
        if number in found:
            return found[number]
    return None


def per_100g_values(food):
    """Macros per 100 g (Foundation/SR Legacy, and Branded foodNutrients)."""
    return {macro: nutrient_amount(food, numbers) for macro, numbers in NUTRIENT_NUMBERS.items()}


def scale(values, grams):
    """Scales per-100 g values to one serving of `grams` grams (None stays None)."""
    return {macro: None if value is None else round(value * grams / 100, 1) for macro, value in values.items()}


def serving_grams(food):
    """A Branded food's serving size in grams, or None if it's given in another unit (e.g. ml)."""
    size, unit = food.get("servingSize"), str(food.get("servingSizeUnit") or "").lower()
    return float(size) if size and unit in GRAM_UNITS else None


def branded_serving_values(food):
    """
    Macros per labelled serving for a Branded food: labelNutrients where present, otherwise
    the per-100 g foodNutrients scaled by a gram serving size.
    """
    label = food.get("labelNutrients") or {}
    grams = serving_grams(food)
    fallback = scale(per_100g_values(food), grams) if grams else {}
    values = {}
    for macro, key in LABEL_KEYS.items():
        value = (label.get(key) or {}).get("value")
        values[macro] = round(float(value), 1) if value is not None else fallback.get(macro)
    return values


def suggest_serving(food):
    """(grams, description) of the first USDA portion with a gram weight, or None."""
    for portion in food.get("foodPortions") or []:
        grams = portion.get("gramWeight")
        if not grams:
            continue
        unit = (portion.get("measureUnit") or {}).get("name")
        unit = "" if unit in (None, "undetermined") else unit
        amount = portion.get("amount")
        parts = [f"{float(amount):g}" if amount else "", unit,
                 portion.get("modifier") or "", portion.get("portionDescription") or ""]
        description = " ".join(p for p in parts if p).strip() or "1 portion"
        return float(grams), description
    return None


def candidate_values(food, grams=None):
    """(per-serving macros, serving grams) for a candidate; per-100 g types need grams."""
    if food.get("dataType") in PER_100G_TYPES:
        return scale(per_100g_values(food), grams), grams
    return branded_serving_values(food), serving_grams(food)


def is_complete(values):
    return all(values.get(m) is not None for m in ("calories", "protein", "carbs", "fat"))


def has_core_macros(food):
    """Whether a candidate reports calories/protein/carbs/fat at all (some FDC records are partial)."""
    values = per_100g_values(food) if food.get("dataType") in PER_100G_TYPES else branded_serving_values(food)
    return is_complete(values)


def fmt(value):
    return "-" if value is None else f"{value:g}"


def comparison_table(product, food, values, grams):
    """Side-by-side text table: our values vs the USDA candidate's, scaled to one serving."""
    basis = (f"{grams:g} g serving" if grams else "labelled serving") if food.get("dataType") not in PER_100G_TYPES \
        else f"scaled from per 100 g to {grams:g} g"
    lines = [
        f"  USDA: {food.get('description')}" + (f" ({food['brandOwner']})" if food.get("brandOwner") else ""),
        f"  fdcId {food.get('fdcId')} · {food.get('dataType')} · {basis}",
        f"  {'':<10}{'ours':>10}{'USDA':>10}",
    ]
    for macro in MACROS:
        lines.append(f"  {macro:<10}{fmt(product[macro]):>10}{fmt(values.get(macro)):>10}")
    if values.get("fiber") is None:
        lines.append("  (USDA lists no fiber; 0 would be recorded)")
    return "\n".join(lines)


# --- overrides file ---

def override_names(path):
    if not os.path.exists(path):
        return set()
    with open(path, newline="") as f:
        return {row["Name"] for row in csv.DictReader(f)}


def append_override(path, name, values, fdc_id, grams):
    new_file = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OVERRIDE_FIELDS, lineterminator="\n")
        if new_file:
            writer.writeheader()
        writer.writerow({
            "Name": name,
            "Calories": fmt(values["calories"]), "Protein": fmt(values["protein"]),
            "Carbs": fmt(values["carbs"]), "Fat": fmt(values["fat"]), "Fiber": fmt(values.get("fiber") or 0),
            "Fdc_Id": fdc_id, "Serving_Grams": "" if grams is None else fmt(grams),
        })


# --- the review loop ---

def grocery_products():
    """[(product, is_trader_joes)] for every grocery food, as setup_db.py would load it from the files."""
    winners = {}
    for label, rows in setup_db.read_sources(with_seeds=True, with_trader_joes=True):
        for row in rows:
            winners[row["name"]] = (row, label == "trader_joes_macros.json")
    return [(row, tj) for row, tj in winners.values() if row["location"] == "Grocery"]


def search_query(product, is_trader_joes):
    if is_trader_joes:
        return f"Trader Joe's {product['name']}", ("Branded",)
    return product["name"], PER_100G_TYPES


def ask_grams(ask, suggestion):
    default = suggestion[0] if suggestion else None
    hint = f" [{default:g} g = {suggestion[1]}]" if suggestion else ""
    while True:
        answer = ask(f"  Grams in one serving{hint}: ").strip()
        if not answer and default:
            return default
        try:
            grams = float(answer)
            if grams > 0:
                return grams
        except ValueError:
            pass
        print("  Please enter a positive number of grams.")


def review_product(client, product, is_trader_joes, overrides_path, dry_run, ask=input):
    """Shows candidates for one food and handles the answer. Returns False if the user quit."""
    query, data_types = search_query(product, is_trader_joes)
    print(f"\n=== {product['name']}  (searching {' / '.join(data_types)} for \"{query}\")")
    hits = client.search(query, data_types, require_all_words=is_trader_joes)
    if not hits:
        print("  No USDA match" + (" (no Branded food contains every word of the name)." if is_trader_joes else "."))
        return True
    details = client.details([hit["fdcId"] for hit in hits])
    foods = [details.get(hit["fdcId"], hit) for hit in hits]
    usable = [has_core_macros(food) for food in foods]
    for n, food in enumerate(foods, start=1):
        brand = f" ({food['brandOwner']})" if food.get("brandOwner") else ""
        missing = "" if usable[n - 1] else "  (no calorie/macro data)"
        print(f"  {n}. {food.get('description')}{brand} [{food.get('dataType')}, fdcId {food.get('fdcId')}]{missing}")

    # Start on the best-ranked candidate that actually has macros
    index = usable.index(True) if any(usable) else 0
    while True:
        food = foods[index]
        grams = None
        if food.get("dataType") in PER_100G_TYPES:
            suggestion = suggest_serving(food)
            grams = (suggestion[0] if suggestion else 100.0) if dry_run else ask_grams(ask, suggestion)
        values, grams = candidate_values(food, grams)
        print(f"\n  Candidate {index + 1}:")
        print(comparison_table(product, food, values, grams))
        if dry_run:
            return True
        if not is_complete(values):
            print("  This candidate is missing calories/protein/carbs/fat and can't be accepted.")
        answer = ask(f"  [y] accept  [n] skip  [1-{len(foods)}] other candidate  [q] quit: ").strip().lower()
        if answer == "y" and is_complete(values):
            append_override(overrides_path, product["name"], values, food.get("fdcId"), grams)
            print(f"  Saved to {os.path.relpath(overrides_path, ROOT)}.")
            return True
        if answer == "n":
            return True
        if answer == "q":
            return False
        if answer.isdigit() and 1 <= int(answer) <= len(foods):
            index = int(answer) - 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="show comparisons without prompting or writing")
    parser.add_argument("--only", metavar="NAME", help="check just this food (exact name)")
    args = parser.parse_args(argv)

    load_dotenv(os.path.join(ROOT, ".env"))
    api_key = os.getenv("USDA_API_KEY")
    if not api_key:
        sys.exit("USDA_API_KEY is not set. Add it to .env (free key: https://fdc.nal.usda.gov/api-key-signup).")
    if not args.dry_run and not sys.stdin.isatty():
        sys.exit("This is interactive; run it in a terminal, or use --dry-run.")

    products = grocery_products()
    if args.only:
        products = [(p, tj) for p, tj in products if p["name"] == args.only]
        if not products:
            sys.exit(f"No grocery food named {args.only!r} (restaurant items aren't looked up).")
    done = override_names(setup_db.USDA_OVERRIDES_PATH)
    todo = [(p, tj) for p, tj in products if p["name"] not in done]
    print(f"{len(todo)} grocery foods to check ({len(products) - len(todo)} already in "
          f"{os.path.relpath(setup_db.USDA_OVERRIDES_PATH, ROOT)})."
          + (" Dry run: nothing will be written." if args.dry_run else ""))

    client = FdcClient(api_key)
    try:
        for product, is_trader_joes in todo:
            if not review_product(client, product, is_trader_joes, setup_db.USDA_OVERRIDES_PATH, args.dry_run):
                break
    except FdcError as e:
        sys.exit(f"Stopped: {e}")
    if not args.dry_run:
        print("\nDone. Run scripts/setup_db.py to load accepted values.")


if __name__ == "__main__":
    main()
