import time
import warnings

import pulp

import solver

# (display name used in plan items, slot name used in food["meal_slots"])
MEALS = [("Breakfast", "breakfast"), ("Lunch", "lunch"), ("Dinner", "dinner"), ("Snack", "snack")]
MAIN_MEALS = ["Breakfast", "Lunch", "Dinner"]
MACROS = ["calories", "protein", "carbs", "fat"]
# Same weights as solver.plan_penalty
MACRO_WEIGHTS = {"calories": 20, "protein": 100, "carbs": 20, "fat": 20}
MAX_FIBER = 35


def meal_location(meal, restaurant, restaurant_meal):
    """Where a meal's foods may come from, matching solver.build_meal_plan's lunch_loc/dinner_loc."""
    if meal in ("Lunch", "Dinner") and restaurant_meal == meal:
        return restaurant
    return "Grocery"


def serving_cap(food, meal):
    """Matches solver.build_meal_plan: snacks are single servings, main meals at most 3."""
    return 1 if meal == "Snack" else min(food["max_servings"], 3)


def eligible_pairs(foods, restaurant, restaurant_meal):
    """(food index, meal) pairs a food may be placed in: right slot, right location, right category."""
    pairs = []
    for meal, slot in MEALS:
        location = meal_location(meal, restaurant, restaurant_meal)
        for i, food in enumerate(foods):
            if slot not in food["meal_slots"] or food.get("location", "Grocery") != location:
                continue
            # Main meals are exactly one staple + one lean_protein; snacks take any category
            if meal != "Snack" and food["category"] not in ("staple", "lean_protein"):
                continue
            pairs.append((i, meal))
    return pairs


def has_required_pools(foods, pairs):
    """Cheap pre-check: every main meal needs a staple and a protein, and the snack needs something."""
    for meal in MAIN_MEALS:
        categories = {foods[i]["category"] for i, m in pairs if m == meal}
        if not {"staple", "lean_protein"} <= categories:
            return False
    return any(m == "Snack" for _, m in pairs)


def build_result(foods, servings, target_calories, target_protein, target_carbs, target_fat):
    """Turns {(food index, meal): servings} into solver.run_heuristic_solver's plan shape."""
    # Same item order as solver.build_meal_plan: breakfast carb first, lunch/dinner protein first
    category_order = {
        "Breakfast": {"staple": 0, "lean_protein": 1},
        "Lunch": {"lean_protein": 0, "staple": 1},
        "Dinner": {"lean_protein": 0, "staple": 1},
        "Snack": {},
    }
    result_items = []
    totals = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}
    for meal, _ in MEALS:
        placed = sorted(
            (i for (i, m) in servings if m == meal),
            key=lambda i: (category_order[meal].get(foods[i]["category"], 0), i),
        )
        for i in placed:
            food, count = foods[i], servings[(i, meal)]
            for key in totals:
                totals[key] += food[key] * count
            result_items.append({
                "name":     food["name"],
                "servings": count,
                "category": food["category"],
                "meal":     meal,
            })

    penalty = solver.plan_penalty(totals, target_calories, target_protein, target_carbs, target_fat)
    totals["fiber"] = round(totals["fiber"], 1)
    return {"items": result_items, "macros": totals, "penalty": penalty}


def infeasible_result(solve_time):
    return {"items": [], "macros": None, "penalty": None, "status": "infeasible", "solve_time": solve_time}


def optimize_meal_plan(foods, target_calories, target_protein, target_carbs, target_fat,
                       restaurant=None, restaurant_meal=None, time_limit=10):
    """
    Finds the meal plan with the lowest solver.py penalty, exactly, as an integer program (CBC via PuLP).

    Uses the same plan structure as solver.build_meal_plan, but fiber <= 35g is a hard
    constraint instead of a penalty. Returns solver.run_heuristic_solver's dict shape plus
    "status" ("optimal", "feasible" if the time limit hit before optimality was proven,
    or "infeasible" if no valid plan exists or none was found in time) and "solve_time"
    in seconds. Infeasible results have no items and None for macros and penalty.
    """
    start = time.perf_counter()
    pairs = eligible_pairs(foods, restaurant, restaurant_meal)
    if not has_required_pools(foods, pairs):
        return infeasible_result(time.perf_counter() - start)

    prob = pulp.LpProblem("meal_plan", pulp.LpMinimize)
    s, y = {}, {}
    for n, (i, meal) in enumerate(pairs):
        cap = serving_cap(foods[i], meal)
        s[i, meal] = prob.add_variable(f"s_{n}", 0, cap, cat="Integer")
        y[i, meal] = prob.add_variable(f"y_{n}", cat="Binary")
        # Food used in this meal <=> at least one serving
        prob += y[i, meal] <= s[i, meal]
        prob += s[i, meal] <= cap * y[i, meal]

    def used(meal, category=None):
        return pulp.lpSum(y[i, m] for (i, m) in pairs
                          if m == meal and (category is None or foods[i]["category"] == category))

    for meal in MAIN_MEALS:
        prob += used(meal, "staple") == 1
        prob += used(meal, "lean_protein") == 1
    prob += used("Snack") >= 1
    prob += used("Snack") <= 2

    # Each food at most once per day (by name, like pick_unique). This also keeps
    # dinner's staple different from lunch's.
    for name in {foods[i]["name"] for i, _ in pairs}:
        prob += pulp.lpSum(y[i, m] for (i, m) in pairs if foods[i]["name"] == name) <= 1

    def total(key):
        return pulp.lpSum(foods[i][key] * s[i, m] for (i, m) in pairs)

    prob += total("fiber") <= MAX_FIBER

    # |total - target| = over + under, with both nonnegative and minimized
    targets = {"calories": target_calories, "protein": target_protein, "carbs": target_carbs, "fat": target_fat}
    objective = []
    for macro in MACROS:
        over = prob.add_variable(f"over_{macro}", 0)
        under = prob.add_variable(f"under_{macro}", 0)
        prob += total(macro) - targets[macro] == over - under
        objective.append(MACRO_WEIGHTS[macro] * (over + under))
    prob += pulp.lpSum(objective)

    # PuLP 3.3 warns that its bundled CBC goes away in 4.0; we pin 3.3 for exactly that bundle.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="PULP_CBC_CMD is deprecated", category=DeprecationWarning)
        cbc = pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit, gapRel=0)
    prob.solve(cbc)
    solve_time = time.perf_counter() - start

    if prob.sol_status == pulp.LpSolutionOptimal:
        status = "optimal"
    elif prob.sol_status == pulp.LpSolutionIntegerFeasible:
        status = "feasible"
    else:
        return infeasible_result(solve_time)

    servings = {}
    for key, var in s.items():
        count = int(round(var.value() or 0))
        if count > 0:
            servings[key] = count

    result = build_result(foods, servings, target_calories, target_protein, target_carbs, target_fat)
    result["status"] = status
    result["solve_time"] = solve_time
    return result
