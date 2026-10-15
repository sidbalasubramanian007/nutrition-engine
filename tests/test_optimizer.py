import random

import pytest

import optimizer
import setup_db
import solver


def food(name, category, meal_slots, max_servings, calories, protein, carbs, fat, fiber, location="Grocery"):
    return {"name": name, "category": category, "meal_slots": meal_slots, "max_servings": max_servings,
            "calories": calories, "protein": protein, "carbs": carbs, "fat": fat, "fiber": fiber,
            "location": location}


# --- a tiny plan that can be solved by hand ---

# Slots and caps force everything except two serving counts:
#   Breakfast: Oats + EggWhites are the only breakfast staple/protein (cap 1 each).
#   Lunch:     Potato is lunch-only, so it must be lunch's staple, leaving Rice for dinner.
#              Chicken is the only lunch protein, so Salmon (dinner-only) is dinner's protein.
#   Snack:     Banana is the only snack, at 1 serving.
# Fixed part (Oats + EggWhites + Potato + Salmon + Banana):
#   calories 545, protein 41, carbs 80, fat 7, fiber 9
# Free: Chicken servings c in 1..3, Rice servings r in 1..3, adding
#   calories 110c + 200r, protein 23c + 4r, carbs 45r, fat 2c, fiber r
# Carbs pin down r and protein then pins down c, so every (c, r) has distinct macros.
# The targets below are exactly the c=2, r=3 totals:
#   calories 545+220+600 = 1365, protein 41+46+12 = 99, carbs 80+135 = 215, fat 7+4 = 11, fiber 9+3 = 12
HAND_FOODS = [
    food("Oats",      "staple",       ["breakfast"],         1, 150, 5,  27, 3, 4),
    food("EggWhites", "lean_protein", ["breakfast"],         1, 50,  11, 0,  0, 0),
    food("Potato",    "staple",       ["lunch"],             1, 110, 3,  26, 0, 2),
    food("Rice",      "staple",       ["lunch", "dinner"],   3, 200, 4,  45, 0, 1),
    food("Chicken",   "lean_protein", ["lunch", "dinner"],   3, 110, 23, 0,  2, 0),
    food("Salmon",    "lean_protein", ["dinner"],            1, 130, 21, 0,  4, 0),
    food("Banana",    "carb",         ["snack"],             2, 105, 1,  27, 0, 3),
]

HAND_PLAN_ITEMS = [
    {"name": "Oats",      "servings": 1, "category": "staple",       "meal": "Breakfast"},
    {"name": "EggWhites", "servings": 1, "category": "lean_protein", "meal": "Breakfast"},
    {"name": "Chicken",   "servings": 2, "category": "lean_protein", "meal": "Lunch"},
    {"name": "Potato",    "servings": 1, "category": "staple",       "meal": "Lunch"},
    {"name": "Salmon",    "servings": 1, "category": "lean_protein", "meal": "Dinner"},
    {"name": "Rice",      "servings": 3, "category": "staple",       "meal": "Dinner"},
    {"name": "Banana",    "servings": 1, "category": "carb",         "meal": "Snack"},
]


@pytest.mark.parametrize("solver_name", ["highs", "cbc"])
def test_optimizer_finds_the_hand_computed_plan(solver_name):
    result = optimizer.optimize_meal_plan(HAND_FOODS, 1365, 99, 215, 11, solver_name=solver_name)

    assert result["status"] == "optimal"
    assert result["solver"] == solver_name
    assert result["items"] == HAND_PLAN_ITEMS
    assert result["macros"] == {"calories": 1365, "protein": 99.0, "carbs": 215.0, "fat": 11.0, "fiber": 12.0}
    assert result["penalty"] == 0.0
    assert result["solve_time"] >= 0


def test_optimizer_uses_solver_weights_when_target_is_unreachable():
    # Protein 100 can't be hit: 41 + 23c + 4r = 100 has no solution with c, r in 1..3.
    # c=2, r=3 is still best (1g short -> 1 * 100 = 100); every other (c, r) misses carbs
    # by 45g+ (900+) or protein by 22g+ (2200+), and the next best plan scores 4440.
    result = optimizer.optimize_meal_plan(HAND_FOODS, 1365, 100, 215, 11)

    assert result["items"] == HAND_PLAN_ITEMS
    assert result["penalty"] == 100.0


# --- structure on the real food data ---

def csv_foods(restaurant=None):
    """food_data.csv read directly (no database), filtered like solver.load_food_data."""
    foods = setup_db.read_food_csv(setup_db.FOOD_DATA_PATH)
    return [f for f in foods if f["location"] == "Grocery" or f["location"] == restaurant]


@pytest.mark.parametrize("restaurant, restaurant_meal", [(None, None), ("Chipotle", "Lunch"), ("CAVA", "Dinner")])
def test_optimizer_plan_structure_on_csv_foods(restaurant, restaurant_meal):
    foods = csv_foods(restaurant)
    by_name = {f["name"]: f for f in foods}

    result = optimizer.optimize_meal_plan(foods, 2800, 170, 390, 68, restaurant, restaurant_meal)
    assert result["status"] == "optimal"
    items = result["items"]

    for meal in ["Breakfast", "Lunch", "Dinner"]:
        categories = sorted(item["category"] for item in items if item["meal"] == meal)
        assert categories == ["lean_protein", "staple"], meal

    staple = {item["meal"]: item["name"] for item in items if item["category"] == "staple" and item["meal"] != "Snack"}
    assert staple["Lunch"] != staple["Dinner"]

    snacks = [item for item in items if item["meal"] == "Snack"]
    assert 1 <= len(snacks) <= 2
    assert all(item["servings"] == 1 for item in snacks)

    names = [item["name"] for item in items]
    assert len(names) == len(set(names))

    for item in items:
        f = by_name[item["name"]]
        assert item["meal"].lower() in f["meal_slots"], item
        assert f["location"] == optimizer.meal_location(item["meal"], restaurant, restaurant_meal), item
        assert 1 <= item["servings"] <= optimizer.serving_cap(f, item["meal"]), item

    assert result["macros"]["fiber"] <= 35


# --- infeasible inputs ---

def test_no_proteins_returns_infeasible_without_raising():
    foods = [f for f in HAND_FOODS if f["category"] != "lean_protein"]
    result = optimizer.optimize_meal_plan(foods, 2000, 150, 250, 60)

    assert result["status"] == "infeasible"
    assert result["items"] == []
    assert result["macros"] is None
    assert result["penalty"] is None


def test_fiber_cap_can_make_the_plan_infeasible():
    # Structurally fine, but the forced breakfast staple alone exceeds 35g fiber,
    # so only CBC (not the pre-check) can tell it's infeasible.
    foods = [dict(f, fiber=40) if f["name"] == "Oats" else f for f in HAND_FOODS]
    result = optimizer.optimize_meal_plan(foods, 1365, 99, 215, 11)

    assert result["status"] == "infeasible"
    assert result["items"] == []


# --- versus the heuristic ---

def test_optimizer_penalty_is_never_worse_than_the_heuristic():
    foods = csv_foods()
    random.seed(0)
    heuristic = solver.run_heuristic_solver(foods, 2800, 170, 390, 68, iterations=50000)

    result = optimizer.optimize_meal_plan(foods, 2800, 170, 390, 68)

    assert result["status"] == "optimal"
    # Small tolerance only for float summation order; both use solver.plan_penalty.
    assert result["penalty"] <= heuristic["penalty"] + 1e-6


def all_grocery_foods():
    """The 39-food grocery pool: food_data.csv + data/seed_*.csv + Trader Joe's, read from files."""
    foods = setup_db.collect_products(with_seeds=True, with_trader_joes=True)
    return [f for f in foods if f["location"] == "Grocery"]


def test_optimizer_penalty_is_never_worse_than_the_heuristic_on_the_full_grocery_pool():
    foods = all_grocery_foods()
    random.seed(0)
    heuristic = solver.run_heuristic_solver(foods, 2800, 170, 390, 68, iterations=50000)

    # Proving optimality on this pool takes ~2-4s on an 8-core laptop and can run past any fixed
    # limit on slower CI machines, so "feasible" (best plan found in time) is accepted too. The
    # generous limit still lets fast machines finish the proof.
    result = optimizer.optimize_meal_plan(foods, 2800, 170, 390, 68, time_limit=60)

    assert result["status"] in ("optimal", "feasible")
    assert result["penalty"] <= heuristic["penalty"] + 1e-6


# --- solver choice, warm start, time limit ---

def test_defaults_to_highs_and_falls_back_to_cbc_without_highspy(monkeypatch):
    assert optimizer.default_solver() == "highs"
    monkeypatch.setattr(optimizer, "highspy", None)
    assert optimizer.default_solver() == "cbc"

    result = optimizer.optimize_meal_plan(HAND_FOODS, 1365, 99, 215, 11)
    assert result["solver"] == "cbc"
    assert result["items"] == HAND_PLAN_ITEMS


def test_warm_start_neither_prints_nor_changes_the_callers_random_state(capsys):
    random.seed(123)
    expected_next = random.random()
    random.seed(123)

    optimizer.optimize_meal_plan(HAND_FOODS, 1365, 99, 215, 11, warm_start_iterations=500)

    assert random.random() == expected_next
    assert capsys.readouterr().out == ""


def test_hitting_the_time_limit_returns_the_best_plan_found_as_feasible():
    # Proving optimality on the full pool takes ~2s; the warm start guarantees a plan
    # to return when the solver is cut off long before that.
    result = optimizer.optimize_meal_plan(all_grocery_foods(), 2800, 170, 390, 68, time_limit=0.05)

    assert result["status"] == "feasible"
    assert result["penalty"] is not None
    assert len(result["items"]) >= 7



# --- restaurant orders ---

def restaurant_menu(restaurant):
    return [f for f in setup_db.read_food_csv(setup_db.FOOD_DATA_PATH) if f["location"] == restaurant]


def meal_targets(count, seed):
    """Per-meal targets roughly a third of the benchmark's daily ranges."""
    rng = random.Random(seed)
    targets = []
    for _ in range(count):
        calories = rng.randint(450, 1300)
        protein = rng.randint(30, 90)
        fat = round(calories * rng.uniform(0.20, 0.40) / 9)
        carbs = max(10, round((calories - 4 * protein - 9 * fat) / 4))
        targets.append((calories, protein, carbs, fat))
    return targets


def order_rule_violations(order, by_name):
    """Every way an order breaks the structure rules (empty list if it follows them all)."""
    violations = []
    names = [item["name"] for item in order["items"]]
    if len(names) != len(set(names)):
        violations.append("item repeated")
    counts = {}
    for item in order["items"]:
        component = by_name[item["name"]]["component_type"]
        counts[component] = counts.get(component, 0) + 1
        max_servings = 2 if component in ("base", "protein") else 1
        if not 1 <= item["servings"] <= max_servings:
            violations.append(f"{item['servings']}x {component} {item['name']}")
    if not 1 <= counts.get("base", 0) <= 2:
        violations.append(f"{counts.get('base', 0)} bases")
    if not 1 <= counts.get("protein", 0) <= 2:
        violations.append(f"{counts.get('protein', 0)} proteins")
    if counts.get("beans", 0) > 1:
        violations.append(f"{counts['beans']} beans")
    if counts.get("topping", 0) + counts.get("sauce", 0) > 4:
        violations.append("more than 4 toppings + sauces")
    return violations


@pytest.mark.parametrize("restaurant", ["Chipotle", "CAVA"])
def test_restaurant_orders_follow_the_structure_rules(restaurant):
    menu = restaurant_menu(restaurant)
    by_name = {f["name"]: f for f in menu}

    for target in meal_targets(15, seed=1):
        order = optimizer.optimize_restaurant_order(menu, *target)
        assert order["status"] == "optimal", target
        assert all(item["meal"] == "Order" for item in order["items"])
        assert order_rule_violations(order, by_name) == [], target


def test_unconstrained_heuristic_only_wins_by_breaking_the_structure_rules():
    # Documents why the MILP is compared against run_restaurant_solver(rules=True): the
    # original (default) heuristic ignores component types, and wherever it scores lower
    # than the MILP, its order breaks the rules (e.g. double beans or sauces, no base).
    rule_breaking = 0
    for restaurant in ["Chipotle", "CAVA"]:
        menu = restaurant_menu(restaurant)
        by_name = {f["name"]: f for f in menu}
        for target in meal_targets(8, seed=2):
            random.seed(0)
            heuristic = solver.run_restaurant_solver(menu, *target, iterations=50000)
            order = optimizer.optimize_restaurant_order(menu, *target)
            violations = order_rule_violations(heuristic, by_name)
            rule_breaking += bool(violations)
            if heuristic["penalty"] < order["penalty"] - 1e-6:
                assert violations, (restaurant, target, heuristic["items"])
    assert rule_breaking >= 1


@pytest.mark.parametrize("restaurant", ["Chipotle", "CAVA"])
def test_restaurant_order_penalty_is_never_worse_than_the_rule_following_heuristic(restaurant):
    # The default heuristic may break the structure rules (e.g. double beans, no base), so the
    # comparable baseline is the heuristic restricted to rule-following orders.
    menu = restaurant_menu(restaurant)
    for target in meal_targets(8, seed=2):
        random.seed(0)
        heuristic = solver.run_restaurant_solver(menu, *target, iterations=50000, rules=True)
        order = optimizer.optimize_restaurant_order(menu, *target)
        assert order["penalty"] <= heuristic["penalty"] + 1e-6, target


def test_restaurant_order_penalty_uses_the_heuristics_formula():
    order = optimizer.optimize_restaurant_order(restaurant_menu("CAVA"), 900, 60, 100, 30)
    assert order["penalty"] == solver.order_penalty(order["macros"], 900, 60, 100, 30)


def test_restaurant_order_without_a_base_is_infeasible():
    menu = [f for f in restaurant_menu("Chipotle") if f["component_type"] != "base"]
    order = optimizer.optimize_restaurant_order(menu, 900, 60, 100, 30)
    assert order["status"] == "infeasible"
    assert order["items"] == []
    assert order["penalty"] is None



# --- locked and excluded foods ---

def lock(name, meal, servings):
    return {"name": name, "meal": meal, "servings": servings}


def placements(plan):
    return [(i["name"], i["meal"], i["servings"]) for i in plan["items"]]


@pytest.mark.parametrize("locked_item", [
    lock("Chicken Breast", "Dinner", 2),
    lock("Sweet Potato", "Lunch", 3),
    lock("Egg Whites", "Breakfast", 1),
    lock("Almonds", "Snack", 1),
])
def test_locked_item_appears_with_exactly_its_servings_in_its_meal(locked_item):
    result = optimizer.optimize_meal_plan(csv_foods(), 2800, 170, 390, 68, locked=[locked_item])

    assert result["status"] == "optimal"
    assert (locked_item["name"], locked_item["meal"], locked_item["servings"]) in placements(result)
    assert [p[0] for p in placements(result)].count(locked_item["name"]) == 1


def test_several_locks_hold_together():
    locks = [lock("Rolled Oats", "Breakfast", 2), lock("Chicken Breast", "Lunch", 1), lock("Almonds", "Snack", 1)]
    result = optimizer.optimize_meal_plan(csv_foods(), 2800, 170, 390, 68, locked=locks)
    assert result["status"] == "optimal"
    assert {(l["name"], l["meal"], l["servings"]) for l in locks} <= set(placements(result))


def test_excluded_food_never_appears_across_targets():
    foods = csv_foods()
    # All three appear in these targets' unrestricted plans (the yogurt in every one)
    excluded = ["Whole Milk Greek Yogurt", "Olive Oil", "Bananas"]
    for target in [(2800, 170, 390, 68), (1800, 140, 180, 60), (3500, 220, 420, 110), (2200, 120, 300, 70)]:
        baseline = optimizer.optimize_meal_plan(foods, *target)
        result = optimizer.optimize_meal_plan(foods, *target, excluded=excluded)
        assert result["status"] == "optimal", target
        assert not {p[0] for p in placements(result)} & set(excluded), target
        # Excluding foods can only make the best plan worse or equal, never better
        assert result["penalty"] >= baseline["penalty"] - 1e-6, target


@pytest.mark.parametrize("locks, excluded, reason", [
    ([lock("Chicken Breast", "Breakfast", 1)], [],
     "'Chicken Breast' can't go in Breakfast: its meal slots are lunch, dinner"),
    ([lock("Egg Whites", "Breakfast", 1), lock("Whey Protein Powder", "Breakfast", 1)], [],
     "2 lean proteins are locked into Breakfast (Egg Whites, Whey Protein Powder); each main meal takes exactly one"),
    ([lock("Jasmine Rice", "Lunch", 1), lock("Sweet Potato", "Lunch", 1)], [],
     "2 staples are locked into Lunch (Jasmine Rice, Sweet Potato); each main meal takes exactly one"),
    ([lock("Peanut Butter", "Lunch", 1)], [],
     "'Peanut Butter' is a fat food, but Lunch takes exactly one staple and one lean protein"),
    ([lock("Chicken Breast", "Lunch", 1), lock("Chicken Breast", "Dinner", 1)], [],
     "'Chicken Breast' is locked into both Lunch and Dinner; each food is used at most once per day"),
    ([lock("Almonds", "Snack", 2)], [], "'Almonds' is locked at 2 servings in Snack; it allows 1 to 1"),
    ([lock("Rolled Oats", "Breakfast", 1)], ["Rolled Oats"], "'Rolled Oats' is both locked and excluded"),
    ([lock("Tofu Scramble", "Lunch", 1)], [], "Locked food 'Tofu Scramble' isn't in the food pool"),
    ([lock("Chipotle Chicken", "Lunch", 1)], [], "'Chipotle Chicken' is a Chipotle item, but Lunch uses Grocery foods"),
    ([lock("Almonds", "Snack", 1), lock("Bananas", "Snack", 1), lock("Peanut Butter", "Snack", 1)], [],
     "3 foods are locked into Snack (Almonds, Bananas, Peanut Butter); the snack has at most 2"),
    ([lock("Rolled Oats", "Breakfast", 1)], ["Egg Whites", "Whey Protein Powder", "Whole Milk Greek Yogurt"],
     "No lean protein is available for Breakfast with the current foods"),
])
def test_invalid_locks_return_infeasible_with_a_reason(locks, excluded, reason):
    foods = setup_db.read_food_csv(setup_db.FOOD_DATA_PATH)  # all locations, so restaurant locks can be tested
    result = optimizer.optimize_meal_plan(foods, 2800, 170, 390, 68, locked=locks, excluded=excluded)
    assert result["status"] == "infeasible"
    assert result["items"] == [] and result["penalty"] is None
    assert result["reason"] == reason


def test_locks_that_leave_no_completion_are_infeasible_from_the_solver():
    # Each lock is valid on its own, but taking both lunch/dinner proteins at lunch-time slots
    # leaves dinner without one: only the solver can see that.
    locks = [lock("Chicken Breast", "Lunch", 1)]
    foods = [f for f in csv_foods() if f["name"] != "Lean Ground Turkey"]
    result = optimizer.optimize_meal_plan(foods, 2800, 170, 390, 68, locked=locks)
    assert result["status"] == "infeasible"
    assert result["reason"].startswith("No plan can complete the meal structure around the locked foods")


def test_too_much_locked_fiber_is_infeasible_with_a_reason():
    foods = [dict(f, fiber=20) if f["name"] in ("Rolled Oats", "Sweet Potato") else f for f in csv_foods()]
    result = optimizer.optimize_meal_plan(foods, 2800, 170, 390, 68,
                                          locked=[lock("Rolled Oats", "Breakfast", 1), lock("Sweet Potato", "Lunch", 1)])
    assert result["reason"] == "The locked foods alone have 40g of fiber; the daily cap is 35g"


@pytest.mark.parametrize("target", [(2800, 170, 390, 68), (2000, 150, 220, 60), (3200, 200, 380, 95)])
def test_locking_every_item_of_an_optimal_plan_reproduces_it(target):
    foods = csv_foods()
    original = optimizer.optimize_meal_plan(foods, *target)
    assert original["status"] == "optimal"

    locks = [lock(i["name"], i["meal"], i["servings"]) for i in original["items"]]
    reproduced = optimizer.optimize_meal_plan(foods, *target, locked=locks)

    assert reproduced["status"] == "optimal"
    assert reproduced["items"] == original["items"]
    assert reproduced["macros"] == original["macros"]
    assert reproduced["penalty"] == original["penalty"]



def test_exclusions_that_leave_no_valid_plan_say_so():
    # Chicken Breast and Lean Ground Turkey are the CSV pool's only lunch/dinner proteins;
    # without chicken, turkey can't cover both meals
    result = optimizer.optimize_meal_plan(csv_foods(), 2800, 170, 390, 68, excluded=["Chicken Breast"])
    assert result["status"] == "infeasible"
    assert result["reason"] == "No plan fits the meal structure (fiber at most 35g) with the foods left after the exclusions"
