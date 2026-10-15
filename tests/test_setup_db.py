import pytest

import setup_db


def test_parse_meal_slots_splits_pipe_separated_values():
    assert setup_db.parse_meal_slots("breakfast|snack", "carb", "Grocery") == ["breakfast", "snack"]


@pytest.mark.parametrize("category, location, expected", [
    ("lean_protein", "Grocery",  ["lunch", "dinner"]),
    ("staple",       "Grocery",  ["breakfast", "lunch", "dinner", "snack"]),
    ("fat",          "Chipotle", ["lunch", "dinner"]),
    ("staple",       "CAVA",     ["lunch", "dinner"]),
])
def test_blank_meal_slots_fall_back_to_default_rule(category, location, expected):
    assert setup_db.parse_meal_slots("", category, location) == expected
    assert setup_db.parse_meal_slots(None, category, location) == expected


def test_unknown_meal_slot_is_rejected():
    with pytest.raises(ValueError, match="brunch"):
        setup_db.parse_meal_slots("breakfast|brunch", "staple", "Grocery")


def test_every_loadable_food_has_meal_slots():
    foods = setup_db.collect_products(with_seeds=True, with_trader_joes=True)
    assert foods
    for food in foods:
        assert food["meal_slots"], food["name"]
        assert set(food["meal_slots"]) <= set(setup_db.MEAL_SLOTS), food["name"]


def test_trader_joes_items_get_default_meal_slots():
    for food in setup_db.read_trader_joes(setup_db.TRADER_JOES_PATH):
        assert food["meal_slots"] == setup_db.default_meal_slots(food["category"], "Grocery")



def test_component_type_is_required_for_restaurant_items():
    assert setup_db.parse_component_type("base", "Chipotle White Rice", "Chipotle") == "base"
    with pytest.raises(ValueError, match="needs a Component_Type"):
        setup_db.parse_component_type("", "Chipotle White Rice", "Chipotle")


def test_component_type_is_blank_for_grocery_items_and_rejects_unknown_values():
    assert setup_db.parse_component_type("", "Rolled Oats", "Grocery") is None
    with pytest.raises(ValueError, match="dessert"):
        setup_db.parse_component_type("dessert", "Chipotle Chips", "Chipotle")


def test_every_restaurant_item_in_the_data_has_a_component_type():
    foods = setup_db.read_food_csv(setup_db.FOOD_DATA_PATH)
    restaurant_foods = [f for f in foods if f["location"] != "Grocery"]
    assert restaurant_foods
    assert all(f["component_type"] in setup_db.COMPONENT_TYPES for f in restaurant_foods)
    assert all(f["component_type"] is None for f in foods if f["location"] == "Grocery")


# --- sources and USDA overrides (temp data files, no database) ---

OVERRIDES_HEADER = "Name,Calories,Protein,Carbs,Fat,Fiber,Fdc_Id,Serving_Grams\n"


def loaded(with_seeds=True, with_trader_joes=True):
    return {p["name"]: p for p in setup_db.collect_products(with_seeds, with_trader_joes)}


def test_rows_are_tagged_with_their_source(small_sources):
    products = loaded()
    assert products["Oats"]["source"] == "manual"            # food_data.csv
    assert products["Tofu"]["source"] == "manual"            # seed file beats Trader Joe's
    assert products["Lemon Muffins"]["source"] == "gemini_estimate"


def test_usda_overrides_replace_macros_only_and_set_source(small_sources, capsys):
    (small_sources / "data" / "usda_overrides.csv").write_text(
        OVERRIDES_HEADER + "Lemon Muffins,420,6,58,19,1.5,1987654,113\nNot Loaded,100,1,1,1,0,1,100\n")
    before = loaded()["Lemon Muffins"]

    after = loaded()["Lemon Muffins"]

    assert {m: after[m] for m in ("calories", "protein", "carbs", "fat", "fiber")} == \
        {"calories": 420, "protein": 6, "carbs": 58, "fat": 19, "fiber": 1.5}
    assert after["source"] == "usda"
    for kept in ("category", "max_servings", "location", "meal_slots", "component_type"):
        assert after[kept] == before[kept], kept
    assert "Applied 1 USDA overrides" in capsys.readouterr().out


def test_overrides_for_foods_not_loaded_this_run_are_skipped(small_sources):
    (small_sources / "data" / "usda_overrides.csv").write_text(OVERRIDES_HEADER + "Lemon Muffins,420,6,58,19,1.5,1,113\n")
    products = loaded(with_trader_joes=False)
    assert "Lemon Muffins" not in products
    assert {p["source"] for p in products.values()} == {"manual"}


def test_overrides_file_is_not_read_as_a_seed_file(small_sources):
    (small_sources / "data" / "usda_overrides.csv").write_text(OVERRIDES_HEADER + "Oats,140,5,24,2.5,4,1,40\n")
    labels = [label for label, _ in setup_db.read_sources(with_seeds=True, with_trader_joes=False)]
    assert labels == ["data/seed_proteins.csv", "food_data.csv"]



@pytest.mark.parametrize("argv, expected", [
    ([], {"with_seeds": False, "with_trader_joes": False}),
    (["--with-seeds"], {"with_seeds": True, "with_trader_joes": False}),
    (["--with-all"], {"with_seeds": True, "with_trader_joes": True}),
    (["--with-trader-joes", "--with-all"], {"with_seeds": True, "with_trader_joes": True}),
])
def test_command_line_flags(monkeypatch, argv, expected):
    calls = []
    monkeypatch.setattr(setup_db, "setup", lambda **kwargs: calls.append(kwargs))
    setup_db.main(argv)
    assert calls == [expected]
