"""fetch_restaurant_menus.py's parsing and food_data.csv mapping, with fixture JSON shaped like Chipotle's (no network)."""
import csv

import pytest

import fetch_restaurant_menus as menus


def nutrition_record(portion_oz, cal, protein, carbs, fat, fiber):
    return {"portion": {"unit": "oz", "value": portion_oz},
            "nutrition": {"tcal": cal, "prot": protein, "carb": carbs, "tfat": fat, "fibe": fiber, "sodi": 0}}


NUTRITION = {"items": {
    "CMG-5001": nutrition_record(4, 210, 4, 40, 4, 1),        # White Rice
    "CMG-5375": nutrition_record(24, 1260, 0, 0, 0, 0),       # White Rice, family size
    "CMG-5051": nutrition_record(4, 130, 8, 22, 1.5, 7),      # Black Beans
    "CMG-101": nutrition_record(4, 180, 32, 0, 7, 0),         # Chicken Bowl -> chicken filling
    "CMG-106": nutrition_record(2.5, 0, 0, 0, 0, 0),          # Veggie Bowl
    "CMG-1001": nutrition_record(4, 230, 2, 8, 22, 6),        # Guacamole
    "CMG-5201": nutrition_record(3.5, 25, 0, 4, 0, 1),        # Fresh Tomato Salsa
    "CMG-5355": nutrition_record(2, 80, 2, 3, 6, 1),          # Cilantro Lime Sauce
    "CMG-1010": {},                                           # Queso: nothing published
}}


def entry(item_type, item_id, name):
    return {"itemType": item_type, "itemId": item_id, "itemName": name}


# White Rice's regular id appears in several entrees; the family size only once
RULES = {"entrees": [
    entry("Bowl", "CMG-101", "Chicken Bowl"),
    entry("Bowl", "CMG-106", "Veggie Bowl"),
    {"contents": [entry("Rice", "CMG-5001", "White Rice"), entry("Rice", "CMG-5001", "White Rice"),
                  entry("Toppings", "CMG-5001", "White Rice")]},
    {"contents": [entry("Rice", "CMG-5375", "White Rice"), entry("Rice", "CMG-5003", "No Rice")]},
    {"contents": [entry("Beans", "CMG-5051", "Black Beans"), entry("Toppings", "CMG-1001", "Guacamole"),
                  entry("Toppings", "CMG-5201", "Fresh Tomato Salsa"),
                  entry("Toppings", "CMG-5355", "Cilantro Lime Sauce"), entry("Toppings", "CMG-1010", "Queso"),
                  entry("Options", "CMG-5254", "No Included Toppings")]},
]}


def parsed():
    return menus.parse_chipotle(NUTRITION, RULES)


def test_parse_joins_names_to_values_with_one_role_per_name():
    items, _ = parsed()
    assert [(i["component_type"], i["name"], i["official_id"]) for i in items] == [
        ("base", "White Rice", "CMG-5001"),      # stays a base though also listed as a topping
        ("protein", "Chicken", "CMG-101"),       # bowl entry -> its protein; Veggie Bowl excluded
        ("beans", "Black Beans", "CMG-5051"),
        ("topping", "Fresh Tomato Salsa", "CMG-5201"),
        ("topping", "Guacamole", "CMG-1001"),
        ("sauce", "Cilantro Lime Sauce", "CMG-5355"),
    ]
    chicken = items[1]
    assert chicken["serving_size"] == {"unit": "oz", "value": 4}
    assert (chicken["calories"], chicken["protein"], chicken["carbs"], chicken["fat"], chicken["fiber"]) == (180, 32, 0, 7, 0)


def test_parse_keeps_the_most_used_id_and_reports_skips():
    _, notes = parsed()
    assert any(n.startswith("White Rice: kept CMG-5001") and "CMG-5375" in n for n in notes)
    assert "Queso (CMG-1010): no complete nutrition published, skipped" in notes
    assert not any("No Rice" in n or "No Included" in n for n in notes)


@pytest.mark.parametrize("component, macros, category, max_servings", [
    ("base", (210, 4, 40, 4), "staple", "2"),
    ("protein", (180, 32, 0, 7), "lean_protein", "2"),
    ("beans", (130, 8, 22, 1.5), "carb", "1"),
    ("topping", (230, 2, 8, 22), "fat", "1"),     # fat calories dominate
    ("topping", (25, 0, 4, 0), "carb", "1"),
    ("sauce", (80, 2, 3, 6), "fat", "1"),
])
def test_csv_row_mapping(component, macros, category, max_servings):
    cal, protein, carbs, fat = macros
    item = {"name": "Thing", "component_type": component, "calories": cal, "protein": protein,
            "carbs": carbs, "fat": fat, "fiber": 1.5}
    row = menus.csv_row("Chipotle", item, menus.CHIPOTLE_URL)
    assert row["Name"] == "Chipotle Thing"
    assert (row["Category"], row["Max_Servings"], row["Component_Type"]) == (category, max_servings, component)
    assert (row["Location"], row["Meal_Slots"], row["Source_Url"]) == ("Chipotle", "lunch|dinner", menus.CHIPOTLE_URL)
    assert row["Fat"] == f"{float(fat):g}" and row["Fiber"] == "1.5"


@pytest.mark.parametrize("url, official", [
    ("https://www.chipotle.com/nutrition-calculator", True),
    ("https://services.chipotle.com/menu-metadata/v1/menu-metadata/nutrition", True),
    ("https://cava.com/", True),
    ("https://notchipotle.com/x", False),
    ("https://chipotle.com.example.net/x", False),
    ("https://www.nutritionix.com/chipotle", False),
])
def test_only_official_domains_count(url, official):
    assert menus.is_official(url) is official


HEADER = ["Name", "Calories", "Protein", "Carbs", "Fat", "Fiber", "Category", "Max_Servings", "Location",
          "Meal_Slots", "Component_Type"]


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(rows)


def test_update_food_data_adds_updates_and_leaves_others(tmp_path):
    path = tmp_path / "food_data.csv"
    write_csv(path, [
        ["Rolled Oats", "150", "5", "27", "2.5", "4", "staple", "3", "Grocery", "breakfast", ""],
        ["Chipotle Chicken", "180", "32", "0", "7", "0", "lean_protein", "2", "Chipotle", "lunch|dinner", "protein"],
        ["Chipotle Black Beans", "130", "8", "22", "1.5", "7", "carb", "2", "Chipotle", "lunch|dinner", "beans"],
        ["Chipotle Old Item", "100", "1", "1", "1", "0", "fat", "1", "Chipotle", "lunch|dinner", "topping"],
        ["CAVA Tzatziki", "40", "1", "3", "3", "0", "fat", "2", "CAVA", "lunch|dinner", "sauce"],
    ])
    items, _ = parsed()
    results = [
        {"restaurant": "Chipotle", "status": "ok", "source_url": menus.CHIPOTLE_URL, "items": items},
        {"restaurant": "CAVA", "status": "blocked", "source_url": menus.CAVA_URL, "saw": "HTTP 403"},
    ]

    added, updated, untouched = menus.update_food_data(results, path)

    assert [r["Name"] for r in added] == ["Chipotle White Rice", "Chipotle Fresh Tomato Salsa",
                                          "Chipotle Guacamole", "Chipotle Cilantro Lime Sauce"]
    assert {name: set(changes) for name, changes in updated} == {
        "Chipotle Chicken": {"Source_Url"},
        "Chipotle Black Beans": {"Max_Servings", "Source_Url"},  # beans are now 1 serving
    }
    assert untouched == ["Chipotle Old Item"]

    rows = {r["Name"]: r for r in csv.DictReader(open(path))}
    assert rows["Rolled Oats"]["Source_Url"] == "" and rows["CAVA Tzatziki"]["Source_Url"] == ""
    assert rows["CAVA Tzatziki"]["Calories"] == "40"  # blocked restaurant: nothing written
    assert rows["Chipotle Old Item"]["Calories"] == "100"
    assert rows["Chipotle Guacamole"]["Source_Url"] == menus.CHIPOTLE_URL
    assert list(rows["Rolled Oats"]) == HEADER + ["Source_Url"]
