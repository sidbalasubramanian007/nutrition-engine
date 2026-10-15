import random

import pytest

import solver

ALL_SLOTS = ["breakfast", "lunch", "dinner", "snack"]
LUNCH_DINNER = ["lunch", "dinner"]


# --- rows_to_foods ---

def test_rows_to_foods_transforms_rows_matching_the_products_query_shape():
    # Column order matches fetch_products_rows()'s SELECT:
    # name, calories, protein, carbs, fat, fiber, category, max_servings, location, meal_slots, component_type, source
    rows = [
        ("Chicken Breast", 110, 23, 0, 2, 0.0, "lean_protein", 6, "Grocery", ["lunch", "dinner"], None, "usda"),
        ("Chipotle White Rice", 210, 4, 40, 4, 1.0, "staple", 2, "Chipotle", ["lunch", "dinner"], "base", "manual"),
    ]
    assert solver.rows_to_foods(rows) == [
        {"name": "Chicken Breast", "calories": 110, "protein": 23, "carbs": 0, "fat": 2,
         "fiber": 0.0, "category": "lean_protein", "max_servings": 6, "location": "Grocery",
         "meal_slots": ["lunch", "dinner"], "component_type": None, "source": "usda"},
        {"name": "Chipotle White Rice", "calories": 210, "protein": 4, "carbs": 40, "fat": 4,
         "fiber": 1.0, "category": "staple", "max_servings": 2, "location": "Chipotle",
         "meal_slots": ["lunch", "dinner"], "component_type": "base", "source": "manual"},
    ]


def test_rows_to_foods_coerces_fiber_to_float():
    # fiber is stored as Postgres FLOAT but psycopg2 can hand back int-like values
    # (e.g. whole-number fiber); rows_to_foods explicitly coerces it to float.
    rows = [("Egg Whites", 50, 11, 0, 0, 0, "lean_protein", 8, "Grocery", ["breakfast"], None, "manual")]
    foods = solver.rows_to_foods(rows)
    assert foods[0]["fiber"] == 0.0
    assert isinstance(foods[0]["fiber"], float)


def test_rows_to_foods_empty_input_returns_empty_list():
    assert solver.rows_to_foods([]) == []


# --- foods_for_slot ---

def test_foods_for_slot_includes_only_foods_whose_meal_slots_contain_the_slot():
    oats = {"name": "Rolled Oats", "category": "staple", "meal_slots": ["breakfast"]}
    banana = {"name": "Bananas", "category": "carb", "meal_slots": ["breakfast", "snack"]}
    rice = {"name": "Jasmine Rice", "category": "staple", "meal_slots": LUNCH_DINNER}
    pool = [oats, banana, rice]
    assert solver.foods_for_slot(pool, "breakfast") == [oats, banana]
    assert solver.foods_for_slot(pool, "snack") == [banana]
    assert solver.foods_for_slot(pool, "lunch") == [rice]


def test_foods_for_slot_ignores_name_and_category():
    # Slots come purely from the data now -- a protein tagged for breakfast is allowed there.
    egg_whites = {"name": "Egg Whites", "category": "lean_protein", "meal_slots": ["breakfast"]}
    assert solver.foods_for_slot([egg_whites], "breakfast") == [egg_whites]
    assert solver.foods_for_slot([egg_whites], "lunch") == []


def test_foods_for_slot_empty_meal_slots_matches_nothing():
    unslotted = {"name": "Nowhere", "category": "staple", "meal_slots": []}
    for slot in ALL_SLOTS:
        assert solver.foods_for_slot([unslotted], slot) == []


# --- pick_unique ---

def test_pick_unique_excludes_already_used_names():
    pool = [{"name": "A"}, {"name": "B"}]
    result = solver.pick_unique(pool, used_names=["A"])
    assert result == {"name": "B"}


def test_pick_unique_returns_none_when_pool_is_exhausted():
    pool = [{"name": "A"}, {"name": "B"}]
    assert solver.pick_unique(pool, used_names=["A", "B"]) is None


def test_pick_unique_returns_none_for_empty_pool():
    assert solver.pick_unique([], used_names=[]) is None


# --- build_meal_plan: scoring / penalty ---

# Fixture foods use the default meal slots setup_db.py assigns to unmapped foods:
# staples fit any slot, lean proteins are lunch/dinner only.
SCORING_FIXTURE_FOODS = [
    {"name": "Oats",      "calories": 150, "protein": 5,  "carbs": 27, "fat": 3, "fiber": 4.0, "category": "staple",       "max_servings": 3, "meal_slots": ALL_SLOTS},
    {"name": "EggWhites", "calories": 50,  "protein": 11, "carbs": 0,  "fat": 0, "fiber": 0.0, "category": "lean_protein", "max_servings": 3, "meal_slots": LUNCH_DINNER},
    {"name": "Rice",      "calories": 200, "protein": 4,  "carbs": 45, "fat": 0, "fiber": 1.0, "category": "staple",       "max_servings": 3, "meal_slots": ALL_SLOTS},
    {"name": "Chicken",   "calories": 110, "protein": 23, "carbs": 0,  "fat": 2, "fiber": 0.0, "category": "lean_protein", "max_servings": 3, "meal_slots": LUNCH_DINNER},
    {"name": "Salmon",    "calories": 130, "protein": 21, "carbs": 0,  "fat": 4, "fiber": 0.0, "category": "lean_protein", "max_servings": 3, "meal_slots": LUNCH_DINNER},
]


@pytest.fixture
def deterministic_random(monkeypatch):
    """
    build_meal_plan's food selection (random.choice) and serving counts
    (random.randint) are both randomized, which makes the scoring logic
    impossible to assert on directly without pinning the RNG. This forces
    every random.choice to take the first available candidate (in fixture
    list order) and every random.randint(a, b) to return `a`, so a given
    foods list always produces the exact same plan.
    """
    monkeypatch.setattr(solver.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(solver.random, "randint", lambda a, b: a)


def test_build_meal_plan_penalty_matches_hand_calculated_value(deterministic_random):
    # With the RNG pinned, this fixture deterministically resolves to:
    #   Breakfast: Oats x1   Lunch: EggWhites x1, Rice x1   Dinner: Chicken x1   Snack: (empty)
    # Totals: calories=510, protein=43, carbs=72, fat=5, fiber=5.0
    plan = solver.build_meal_plan(
        SCORING_FIXTURE_FOODS,
        target_calories=510, target_protein=40, target_carbs=70, target_fat=5,
    )

    assert plan["macros"] == {"calories": 510, "protein": 43.0, "carbs": 72.0, "fat": 5.0, "fiber": 5.0}

    # penalty = |510-510|*20 + |43-40|*100 + |72-70|*20 + |5-5|*20 + max(0, 5.0-35)*50
    #         =        0     +     300     +    40      +    0     +         0
    assert plan["penalty"] == 340.0

    assert plan["items"] == [
        {"name": "Oats",      "servings": 1, "category": "staple",       "meal": "Breakfast"},
        {"name": "EggWhites", "servings": 1, "category": "lean_protein", "meal": "Lunch"},
        {"name": "Rice",      "servings": 1, "category": "staple",       "meal": "Lunch"},
        {"name": "Chicken",   "servings": 1, "category": "lean_protein", "meal": "Dinner"},
    ]


def test_build_meal_plan_penalty_scales_with_target_distance(deterministic_random):
    # Same deterministic plan as above (totals: 510/43/72/5/5.0), but targets moved
    # further away, isolating each weighted term:
    #   calories term: |510-1010|*20 = 10000
    #   protein term:  |43-20|*100   = 2300
    #   carbs term:    |72-20|*20    = 1040
    #   fat term:      |5-25|*20     = 400
    #   fiber term:    max(0, 5-35)*50 = 0
    # total = 13740
    plan = solver.build_meal_plan(
        SCORING_FIXTURE_FOODS,
        target_calories=1010, target_protein=20, target_carbs=20, target_fat=25,
    )
    assert plan["penalty"] == 13740.0


def test_build_meal_plan_penalizes_fiber_only_above_35g(deterministic_random):
    high_fiber_foods = [
        {"name": "Oats",      "calories": 150, "protein": 5,  "carbs": 27, "fat": 3, "fiber": 40.0, "category": "staple",       "max_servings": 3, "meal_slots": ALL_SLOTS},
        {"name": "EggWhites", "calories": 50,  "protein": 11, "carbs": 0,  "fat": 0, "fiber": 0.0,  "category": "lean_protein", "max_servings": 3, "meal_slots": LUNCH_DINNER},
        {"name": "Rice",      "calories": 200, "protein": 4,  "carbs": 45, "fat": 0, "fiber": 0.0,  "category": "staple",       "max_servings": 3, "meal_slots": ALL_SLOTS},
        {"name": "Chicken",   "calories": 110, "protein": 23, "carbs": 0,  "fat": 2, "fiber": 0.0,  "category": "lean_protein", "max_servings": 3, "meal_slots": LUNCH_DINNER},
    ]
    plan = solver.build_meal_plan(
        high_fiber_foods,
        target_calories=510, target_protein=40, target_carbs=70, target_fat=5,
    )
    # fiber total = 40.0 (only Oats contributes) -> excess = 40-35 = 5 -> +250 penalty
    assert plan["macros"]["fiber"] == 40.0
    assert plan["penalty"] == 340.0 + 250.0


def test_build_meal_plan_returns_none_when_pools_are_missing_required_categories():
    # No lean_protein items at all -> lunch_prots/dinner_prots are empty -> invalid day
    no_protein_foods = [
        {"name": "Oats", "calories": 150, "protein": 5, "carbs": 27, "fat": 3, "fiber": 4.0, "category": "staple", "max_servings": 3, "meal_slots": ALL_SLOTS},
    ]
    assert solver.build_meal_plan(no_protein_foods, 2000, 150, 250, 60) is None


# --- build_meal_plan: "anti-spam" serving caps ---

def test_build_meal_plan_caps_servings_at_three_even_with_high_max_servings(monkeypatch):
    # Anti-spam guardrail: max_servings=10 on a food must never translate into more
    # than 3 actual servings for a main-meal item. Pin random.randint to always return
    # the upper bound so the cap (not the RNG) is what determines the result.
    monkeypatch.setattr(solver.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(solver.random, "randint", lambda a, b: b)

    foods = [
        {"name": "S1", "category": "staple",       "max_servings": 10, "calories": 100, "protein": 1,  "carbs": 10, "fat": 1, "fiber": 1.0, "meal_slots": ALL_SLOTS},
        {"name": "S2", "category": "staple",       "max_servings": 10, "calories": 100, "protein": 1,  "carbs": 10, "fat": 1, "fiber": 1.0, "meal_slots": ALL_SLOTS},
        {"name": "S3", "category": "staple",       "max_servings": 10, "calories": 100, "protein": 1,  "carbs": 10, "fat": 1, "fiber": 1.0, "meal_slots": ALL_SLOTS},
        {"name": "S4", "category": "staple",       "max_servings": 10, "calories": 100, "protein": 1,  "carbs": 10, "fat": 1, "fiber": 1.0, "meal_slots": ALL_SLOTS},
        {"name": "P1", "category": "lean_protein", "max_servings": 3,  "calories": 100, "protein": 20, "carbs": 0,  "fat": 2, "fiber": 0.0, "meal_slots": LUNCH_DINNER},
    ]

    plan = solver.build_meal_plan(foods, target_calories=1000, target_protein=50, target_carbs=100, target_fat=20)

    items_by_meal = {(item["name"], item["meal"]): item["servings"] for item in plan["items"]}
    # S1 (breakfast), P1 + S2 (lunch), S3 (dinner) are all main-meal items with max_servings=10,
    # capped at 3 -- never the raw 10 that random.randint(a, b=10) would otherwise return.
    assert items_by_meal[("S1", "Breakfast")] == 3
    assert items_by_meal[("P1", "Lunch")] == 3
    assert items_by_meal[("S2", "Lunch")] == 3
    assert items_by_meal[("S3", "Dinner")] == 3


def test_build_meal_plan_caps_snack_servings_at_one_regardless_of_max_servings(monkeypatch):
    # Same fixture as above: S4 is left over for the Snack slot with max_servings=10,
    # but snacks are hardcoded to a single portion.
    monkeypatch.setattr(solver.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(solver.random, "randint", lambda a, b: b)

    foods = [
        {"name": "S1", "category": "staple",       "max_servings": 10, "calories": 100, "protein": 1,  "carbs": 10, "fat": 1, "fiber": 1.0, "meal_slots": ALL_SLOTS},
        {"name": "S2", "category": "staple",       "max_servings": 10, "calories": 100, "protein": 1,  "carbs": 10, "fat": 1, "fiber": 1.0, "meal_slots": ALL_SLOTS},
        {"name": "S3", "category": "staple",       "max_servings": 10, "calories": 100, "protein": 1,  "carbs": 10, "fat": 1, "fiber": 1.0, "meal_slots": ALL_SLOTS},
        {"name": "S4", "category": "staple",       "max_servings": 10, "calories": 100, "protein": 1,  "carbs": 10, "fat": 1, "fiber": 1.0, "meal_slots": ALL_SLOTS},
        {"name": "P1", "category": "lean_protein", "max_servings": 3,  "calories": 100, "protein": 20, "carbs": 0,  "fat": 2, "fiber": 0.0, "meal_slots": LUNCH_DINNER},
    ]

    plan = solver.build_meal_plan(foods, target_calories=1000, target_protein=50, target_carbs=100, target_fat=20)

    snack_items = [item for item in plan["items"] if item["meal"] == "Snack"]
    assert snack_items == [{"name": "S4", "servings": 1, "category": "staple", "meal": "Snack"}]


def test_build_meal_plan_never_repeats_a_food_across_meals(monkeypatch):
    # "Diversity" guarantee: pick_unique's used-names tracking means no food name
    # should appear twice in one day's plan, even when the same pool is reused
    # for multiple slots (e.g. meal_carbs is queried for both lunch and dinner).
    monkeypatch.setattr(solver.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(solver.random, "randint", lambda a, b: a)

    plan = solver.build_meal_plan(
        SCORING_FIXTURE_FOODS,
        target_calories=2800, target_protein=170, target_carbs=390, target_fat=68,
    )
    names = [item["name"] for item in plan["items"]]
    assert len(names) == len(set(names))


# --- run_heuristic_solver: full solve against a small fixture ---

def test_run_heuristic_solver_picks_the_best_of_several_plans(monkeypatch):
    # With the RNG pinned, build_meal_plan is fully deterministic for a given foods
    # list, so every iteration of run_heuristic_solver produces the identical plan
    # verified in test_build_meal_plan_penalty_matches_hand_calculated_value above.
    # This confirms the solver loop actually surfaces that plan as the winner.
    monkeypatch.setattr(solver.random, "choice", lambda seq: seq[0])
    monkeypatch.setattr(solver.random, "randint", lambda a, b: a)

    winner = solver.run_heuristic_solver(
        SCORING_FIXTURE_FOODS,
        target_calories=510, target_protein=40, target_carbs=70, target_fat=5,
        iterations=5,
    )

    assert winner["penalty"] == 340.0
    assert winner["macros"] == {"calories": 510, "protein": 43.0, "carbs": 72.0, "fat": 5.0, "fiber": 5.0}


def test_run_heuristic_solver_returns_none_when_no_valid_plan_exists():
    no_protein_foods = [
        {"name": "Oats", "calories": 150, "protein": 5, "carbs": 27, "fat": 3, "fiber": 4.0, "category": "staple", "max_servings": 3, "meal_slots": ALL_SLOTS},
    ]
    assert solver.run_heuristic_solver(no_protein_foods, iterations=10) is None

# --- meal slots from the real data files ---

def load_all_real_foods():
    """Every food setup_db.py can load (food_data.csv + data/seed_*.csv + Trader Joe's), in solver shape."""
    import setup_db
    return setup_db.collect_products(with_seeds=True, with_trader_joes=True)


def test_steak_and_salmon_are_never_tagged_for_breakfast_in_the_data():
    foods = load_all_real_foods()
    steak_and_salmon = [f for f in foods if "Steak" in f["name"] or "Salmon" in f["name"]]
    # Sirloin Steak, Wild Sockeye Salmon, Chipotle Steak, CAVA Grilled Steak
    assert len(steak_and_salmon) >= 4
    for food in steak_and_salmon:
        assert "breakfast" not in food["meal_slots"], food["name"]


@pytest.mark.parametrize("restaurant, restaurant_meal", [(None, None), ("Chipotle", "Lunch"), ("CAVA", "Dinner")])
def test_steak_and_salmon_never_land_in_breakfast_across_many_plans(restaurant, restaurant_meal):
    foods = [f for f in load_all_real_foods() if f["location"] in ("Grocery", restaurant)]
    random.seed(0)
    for _ in range(2000):
        plan = solver.build_meal_plan(foods, 2800, 170, 390, 68, restaurant, restaurant_meal)
        breakfast = [item["name"] for item in plan["items"] if item["meal"] == "Breakfast"]
        assert not any("Steak" in name or "Salmon" in name for name in breakfast), breakfast



# --- restaurant orders ---

def restaurant_menu(restaurant):
    import setup_db
    return [f for f in setup_db.read_food_csv(setup_db.FOOD_DATA_PATH) if f["location"] == restaurant]


@pytest.mark.parametrize("restaurant", ["Chipotle", "CAVA"])
def test_rules_mode_only_builds_orders_that_follow_the_structure_rules(restaurant):
    menu = restaurant_menu(restaurant)
    by_name = {f["name"]: f for f in menu}
    random.seed(0)
    for _ in range(500):
        order = solver.build_restaurant_order(menu, 900, 60, 100, 30, rules=True)
        counts = {}
        for item in order["items"]:
            food = by_name[item["name"]]
            counts[food["component_type"]] = counts.get(food["component_type"], 0) + 1
            assert 1 <= item["servings"] <= solver.order_serving_cap(food)
        assert 1 <= counts.get("base", 0) <= 2
        assert 1 <= counts.get("protein", 0) <= 2
        assert counts.get("beans", 0) <= 1
        assert counts.get("topping", 0) + counts.get("sauce", 0) <= 4


def test_rules_mode_returns_none_when_the_menu_has_no_base():
    menu = [f for f in restaurant_menu("Chipotle") if f["component_type"] != "base"]
    assert solver.build_restaurant_order(menu, 900, 60, 100, 30, rules=True) is None
