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
