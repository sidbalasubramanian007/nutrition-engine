"""Fetches per-ingredient nutrition from the restaurants' official sites, and optionally updates food_data.csv.

Usage (from the repo root):
    python scripts/fetch_restaurant_menus.py                      # fetch, print, write data/restaurant_menus_raw.json
    python scripts/fetch_restaurant_menus.py --update-food-data   # ...and merge the results into food_data.csv

Rules this script follows:
  - Only data served by chipotle.com / cava.com (and their own subdomains) is used. There is no
    fallback to third-party sites and no value is ever estimated.
  - One page load per restaurant, in a real browser (Playwright with the installed Chrome).
  - If an official source can't be read, the script says what it saw and exits non-zero for that
    restaurant; nothing is written to food_data.csv for it.

Chipotle: https://www.chipotle.com/nutrition-calculator loads two JSON documents from
services.chipotle.com: menu-metadata/nutrition (values per ingredient id) and
universalmenus/menurules (ingredient names and types). They are joined by id. A protein's
regular portion is the nutrition record of its bowl entry (e.g. "Chicken Bowl"), which the
calculator uses as the filling; it is exactly half the "Extra" portion for most proteins.

CAVA: cava.com is loaded once; if it serves a bot challenge or no nutrition source, that's reported.
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_PATH = os.path.join(ROOT, "data", "restaurant_menus_raw.json")
FOOD_DATA_PATH = os.path.join(ROOT, "food_data.csv")

CHIPOTLE_URL = "https://www.chipotle.com/nutrition-calculator"
CHIPOTLE_NUTRITION = "/menu-metadata/v1/menu-metadata/nutrition"
CHIPOTLE_RULES = "/menuinnovation/v1/universalmenus/menurules"
CAVA_URL = "https://cava.com/"
OFFICIAL_DOMAINS = ("chipotle.com", "cava.com")

# Chipotle dressings; every other "Toppings" item is a topping
CHIPOTLE_SAUCES = {"Chipotle-Honey Vinaigrette", "Cilantro Lime Sauce"}
NUTRITION_KEYS = {"calories": "tcal", "protein": "prot", "carbs": "carb", "fat": "tfat", "fiber": "fibe"}


def is_official(url):
    host = urlparse(url).hostname or ""
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


# --- Chipotle parsing (pure, testable without a browser) ---

def menu_entries(rules):
    """{(itemType, itemId): itemName} from the menurules document."""
    entries = {}

    def walk(node):
        if isinstance(node, dict):
            if "itemId" in node and "itemName" in node and "itemType" in node:
                entries.setdefault((node["itemType"], node["itemId"]), node["itemName"].strip())
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(rules)
    return entries


ROLE_ORDER = {"base": 0, "protein": 1, "beans": 2, "topping": 3, "sauce": 4}


def chipotle_candidates(entries):
    """(component_type, name, itemId) for every ingredient we use, in menu order of type."""
    out = []
    for (item_type, item_id), name in entries.items():
        if name.startswith("No "):  # "No Rice", "No Included Toppings", ...
            continue
        if item_type == "Rice":
            out.append(("base", name, item_id))
        elif item_type == "Beans":
            out.append(("beans", name, item_id))
        elif item_type == "Bowl" and name.endswith(" Bowl") and name != "Veggie Bowl":
            out.append(("protein", name[: -len(" Bowl")].strip(), item_id))
        elif item_type == "Toppings":
            out.append(("sauce" if name in CHIPOTLE_SAUCES else "topping", name, item_id))
    return sorted(out, key=lambda c: (ROLE_ORDER[c[0]], c[1], c[2]))


def parse_chipotle(nutrition, rules):
    """
    Joins names (menurules) to values (menu-metadata/nutrition). Returns (items, notes).

    Each name is used once, in its first role by ROLE_ORDER (rice listed among toppings stays a
    base). When a name has several ids (e.g. a 24 oz family size), the one used most across the
    menu, the individual serving, is kept. Notes list skipped ingredients and the ids not kept.
    """
    text = json.dumps(rules)
    usage = lambda item_id: text.count(f'"{item_id}"')
    by_name = {}
    for component, name, item_id in chipotle_candidates(menu_entries(rules)):
        by_name.setdefault(name, []).append((component, item_id))

    items, notes = [], []
    for name, options in by_name.items():
        component = min((c for c, _ in options), key=ROLE_ORDER.get)
        ids = sorted({i for c, i in options if c == component}, key=lambda i: (-usage(i), i))
        item_id, others = ids[0], ids[1:]
        record = nutrition.get("items", {}).get(item_id) or {}
        values = record.get("nutrition") or {}
        if any(values.get(key) is None for key in NUTRITION_KEYS.values()):
            notes.append(f"{name} ({item_id}): no complete nutrition published, skipped")
            continue
        if others:
            sizes = ", ".join(f"{i} ({(nutrition['items'].get(i) or {}).get('portion')})" for i in others)
            notes.append(f"{name}: kept {item_id} ({record.get('portion')}), the most used id; also listed as {sizes}")
        items.append({
            "name": name,
            "official_id": item_id,
            "component_type": component,
            "serving_size": record.get("portion"),
            **{field: values[key] for field, key in NUTRITION_KEYS.items()},
        })
    items.sort(key=lambda it: (ROLE_ORDER[it["component_type"]], it["name"]))
    return items, notes


# --- browser fetches (one page load each) ---

def fetch_chipotle(browser):
    page = browser.new_page()
    documents = {}

    def on_response(response):
        if not is_official(response.url):
            return
        for key, fragment in (("nutrition", CHIPOTLE_NUTRITION), ("rules", CHIPOTLE_RULES)):
            if fragment in response.url and key not in documents and response.status == 200:
                try:
                    documents[key] = (response.url, response.json())
                except Exception:
                    pass

    page.on("response", on_response)
    result = {"restaurant": "Chipotle", "source_url": CHIPOTLE_URL}
    try:
        response = page.goto(CHIPOTLE_URL, wait_until="domcontentloaded", timeout=60000)
        for _ in range(60):  # wait up to 30s for the calculator's data
            if len(documents) == 2:
                break
            page.wait_for_timeout(500)
        if len(documents) < 2:
            missing = {"nutrition", "rules"} - set(documents)
            return {**result, "status": "unreadable",
                    "saw": f"HTTP {response.status if response else '?'}, title {page.title()!r}; "
                           f"the calculator never loaded its {', '.join(sorted(missing))} data"}
        items, notes = parse_chipotle(documents["nutrition"][1], documents["rules"][1])
        if not items:
            return {**result, "status": "unreadable", "saw": "the calculator's data had no recognisable ingredients"}
        return {**result, "status": "ok", "data_urls": [documents["nutrition"][0], documents["rules"][0]],
                "items": items, "notes": notes}
    finally:
        page.close()


def fetch_cava(browser):
    page = browser.new_page()
    result = {"restaurant": "CAVA", "source_url": CAVA_URL}
    try:
        response = page.goto(CAVA_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        title = page.title()
        text = " ".join(page.locator("body").inner_text().split())[:300]
        status = response.status if response else None
        if status in (403, 429, 503) or "just a moment" in title.lower() or "security verification" in text.lower():
            return {**result, "status": "blocked", "saw": f"HTTP {status}, title {title!r}: {text}"}
        links = page.eval_on_selector_all(
            "a[href]", "as => as.map(a => a.href).filter(h => /nutri|allergen|calor/i.test(h))")
        official = sorted({link for link in links if is_official(link)})
        # A nutrition page would need a second page load, which this script doesn't do
        return {**result, "status": "unreadable",
                "saw": f"HTTP {status}, title {title!r}; nutrition links on cava.com: {official or 'none'}"}
    finally:
        page.close()


# --- food_data.csv mapping ---

def csv_row(restaurant, item, source_url):
    """An official item as a food_data.csv row (see the README for the mapping rules)."""
    component = item["component_type"]
    if component == "base":
        category = "staple"
    elif component == "protein":
        category = "lean_protein"
    elif component == "beans":
        category = "carb"
    else:
        # Toppings and sauces by where their calories come from (fat at 9 kcal/g vs carbs at 4)
        category = "fat" if item["fat"] * 9 >= item["carbs"] * 4 else "carb"
    return {
        "Name": f"{restaurant} {item['name']}",
        "Calories": fmt(item["calories"]), "Protein": fmt(item["protein"]), "Carbs": fmt(item["carbs"]),
        "Fat": fmt(item["fat"]), "Fiber": fmt(item["fiber"]),
        "Category": category,
        "Max_Servings": "2" if component in ("base", "protein") else "1",
        "Location": restaurant,
        "Meal_Slots": "lunch|dinner",
        "Component_Type": component,
        "Source_Url": source_url,
    }


def fmt(value):
    return f"{float(value):g}"


def update_food_data(results, path=FOOD_DATA_PATH):
    """Adds/updates rows for restaurants read successfully. Returns (added, updated, untouched) names."""
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames)
        rows = list(reader)
    if "Source_Url" not in fields:
        fields.append("Source_Url")
    for row in rows:
        row.setdefault("Source_Url", "")

    index = {row["Name"]: i for i, row in enumerate(rows)}
    added, updated, untouched = [], [], []
    for result in results:
        if result["status"] != "ok":
            continue
        restaurant = result["restaurant"]
        official_names = set()
        for item in result["items"]:
            new = csv_row(restaurant, item, result["source_url"])
            official_names.add(new["Name"])
            if new["Name"] in index:
                old = rows[index[new["Name"]]]
                changes = {k: (old.get(k, ""), v) for k, v in new.items() if old.get(k, "") != v}
                if changes:
                    old.update(new)
                    updated.append((new["Name"], changes))
            else:
                rows.append(new)
                index[new["Name"]] = len(rows) - 1
                added.append(new)
        untouched += [r["Name"] for r in rows if r["Location"] == restaurant and r["Name"] not in official_names]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    return added, updated, untouched


# --- output ---

def print_table(result):
    print(f"\n=== {result['restaurant']}: {result['status']}  ({result['source_url']})")
    if result["status"] != "ok":
        print(f"    Saw: {result['saw']}")
        return
    print(f"    {'Type':<8} {'Ingredient':<28} {'Serving':>10} {'kcal':>6} {'Protein':>8} {'Carbs':>6} {'Fat':>5} {'Fiber':>6}")
    for item in result["items"]:
        size = item["serving_size"] or {}
        serving = f"{fmt(size['value'])} {size['unit']}" if size.get("value") is not None else "-"
        print(f"    {item['component_type']:<8} {item['name']:<28} {serving:>10} {fmt(item['calories']):>6} "
              f"{fmt(item['protein']):>8} {fmt(item['carbs']):>6} {fmt(item['fat']):>5} {fmt(item['fiber']):>6}")
    for note in result["notes"]:
        print(f"    Note: {note}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update-food-data", action="store_true", help="merge successful results into food_data.csv")
    args = parser.parse_args(argv)

    from playwright.sync_api import sync_playwright

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            results = [fetch_chipotle(browser), fetch_cava(browser)]
        finally:
            browser.close()
    for result in results:
        result["fetched_at"] = fetched_at
        print_table(result)

    with open(RAW_PATH, "w") as f:
        json.dump({"fetched_at": fetched_at, "restaurants": results}, f, indent=2)
    print(f"\nWrote {os.path.relpath(RAW_PATH, ROOT)}")

    if args.update_food_data:
        added, updated, untouched = update_food_data(results)
        print(f"\nfood_data.csv: {len(added)} added, {len(updated)} updated")
        for row in added:
            print(f"  + {row['Name']}")
        for name, changes in updated:
            print(f"  ~ {name}: " + ", ".join(f"{k} {old!r} -> {new!r}" for k, (old, new) in changes.items()))
        for name in untouched:
            print(f"  = {name}: not in the official data, left as is")

    failed = [r["restaurant"] for r in results if r["status"] != "ok"]
    if failed:
        print(f"\nCould not read official data for: {', '.join(failed)}. Nothing was written for them.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
