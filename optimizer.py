import contextlib
import io
import os
import random
import time
import warnings

import pulp

import solver

try:
    import highspy
except ImportError:  # HiGHS is optional; the optimizers fall back to CBC
    highspy = None

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


CATEGORY_LABELS = {"staple": "staple", "lean_protein": "lean protein"}


def missing_pool(foods, pairs):
    """Cheap pre-check: why the pools can't fill the meal structure, or None if they might."""
    for meal in MAIN_MEALS:
        categories = {foods[i]["category"] for i, m in pairs if m == meal}
        for category, label in CATEGORY_LABELS.items():
            if category not in categories:
                return f"No {label} is available for {meal} with the current foods"
    if not any(m == "Snack" for _, m in pairs):
        return "No food is available for the snack with the current foods"
    return None


def lock_conflict(foods, locked, excluded, restaurant, restaurant_meal):
    """
    Checks locks ({name, meal, servings}) against the pool and the meal structure before any model
    is built. foods must already exclude the excluded names. Returns why they conflict, or None.
    """
    by_name = {f["name"]: f for f in foods}
    meal_names = [meal for meal, _ in MEALS]
    placed = {}
    for lock in locked:
        name, meal, servings = lock["name"], lock["meal"], lock["servings"]
        if name in excluded:
            return f"'{name}' is both locked and excluded"
        food = by_name.get(name)
        if food is None:
            return f"Locked food '{name}' isn't in the food pool"
        if meal not in meal_names:
            return f"'{name}' is locked into '{meal}', which isn't a meal (use {', '.join(meal_names)})"
        if name in placed:
            return f"'{name}' is locked into both {placed[name]} and {meal}; each food is used at most once per day"
        if meal.lower() not in food["meal_slots"]:
            return f"'{name}' can't go in {meal}: its meal slots are {', '.join(food['meal_slots'])}"
        location = meal_location(meal, restaurant, restaurant_meal)
        if food.get("location", "Grocery") != location:
            return f"'{name}' is a {food.get('location', 'Grocery')} item, but {meal} uses {location} foods"
        if meal != "Snack" and food["category"] not in CATEGORY_LABELS:
            return (f"'{name}' is a {food['category']} food, but {meal} takes exactly one staple "
                    f"and one lean protein")
        cap = serving_cap(food, meal)
        if not 1 <= servings <= cap:
            return f"'{name}' is locked at {servings} servings in {meal}; it allows 1 to {cap}"
        placed[name] = meal

    for meal in meal_names:
        names = [lock["name"] for lock in locked if lock["meal"] == meal]
        if meal == "Snack":
            if len(names) > 2:
                return f"{len(names)} foods are locked into Snack ({', '.join(names)}); the snack has at most 2"
            continue
        for category, label in CATEGORY_LABELS.items():
            same = [n for n in names if by_name[n]["category"] == category]
            if len(same) > 1:
                return f"{len(same)} {label}s are locked into {meal} ({', '.join(same)}); each main meal takes exactly one"

    fiber = sum(by_name[lock["name"]]["fiber"] * lock["servings"] for lock in locked)
    if fiber > MAX_FIBER:
        return f"The locked foods alone have {fiber:g}g of fiber; the daily cap is {MAX_FIBER}g"
    return None


def plan_has_locks(plan, locked):
    placed = {(item["name"], item["meal"], item["servings"]) for item in plan["items"]}
    return all((lock["name"], lock["meal"], lock["servings"]) in placed for lock in locked)


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


def infeasible_result(solve_time, solver_name, reason=None):
    return {"items": [], "macros": None, "penalty": None, "status": "infeasible",
            "solve_time": solve_time, "solver": solver_name, "reason": reason}


def default_solver():
    return "highs" if highspy is not None and pulp.HiGHS(msg=False).available() else "cbc"


if highspy is not None:
    class _WarmStartHiGHS(pulp.HiGHS):
        """pulp.HiGHS ignores initial values; this hands them to HiGHS as the starting incumbent."""

        def callSolver(self, lp):
            solution = highspy.HighsSolution()
            solution.col_value = [v.varValue if v.varValue is not None else 0.0 for v in lp.variables()]
            solution.value_valid = True
            lp.solverModel.setSolution(solution)
            super().callSolver(lp)


def make_solver(name, time_limit, gap_rel, warm_start):
    if name == "highs":
        cls = _WarmStartHiGHS if warm_start else pulp.HiGHS
        # Presolve off measured ~25% faster on the 39-food pool; this model is already tight.
        return cls(msg=False, timeLimit=time_limit, gapRel=gap_rel, presolve="off")
    # PuLP 3.3 warns that its bundled CBC goes away in 4.0; we pin 3.3 for exactly that bundle.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="PULP_CBC_CMD is deprecated", category=DeprecationWarning)
        # CBC's branch-and-bound parallelizes well here (6.6s -> 1.6s on 8 cores).
        return pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit, gapRel=gap_rel, threads=os.cpu_count())


def heuristic_start(foods, targets, restaurant, restaurant_meal, iterations, seed=0):
    """A quick seeded heuristic plan, without printing or disturbing the caller's random state."""
    state = random.getstate()
    random.seed(seed)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return solver.run_heuristic_solver(foods, targets["calories"], targets["protein"], targets["carbs"],
                                               targets["fat"], iterations=iterations,
                                               restaurant=restaurant, restaurant_meal=restaurant_meal)
    finally:
        random.setstate(state)


def total_range(foods, pairs, macro):
    """Lowest and highest possible daily total of a macro, given the per-meal structure."""
    low = high = 0.0
    for meal in MAIN_MEALS:
        for category in ("staple", "lean_protein"):
            options = [(foods[i][macro], serving_cap(foods[i], m))
                       for i, m in pairs if m == meal and foods[i]["category"] == category]
            low += min(value for value, _ in options)
            high += max(value * cap for value, cap in options)
    snack_values = sorted(foods[i][macro] for i, m in pairs if m == "Snack")
    low += snack_values[0]
    high += sum(snack_values[-2:])
    return low, high


def add_deviation_objective(prob, totals, targets, ranges):
    """
    Sets the objective to the weighted absolute deviation from the targets (solver.py's weights).

    |total - target| = over + under, with both nonnegative, bounded by the reachable
    (low, high) totals in ranges, and minimized. Returns {macro: (over, under)}.
    """
    objective, deviation = [], {}
    for macro in MACROS:
        low, high = ranges[macro]
        over = prob.add_variable(f"over_{macro}", 0, max(0, high - targets[macro]))
        under = prob.add_variable(f"under_{macro}", 0, max(0, targets[macro] - low))
        deviation[macro] = (over, under)
        prob += totals[macro] - targets[macro] == over - under
        objective.append(MACRO_WEIGHTS[macro] * (over + under))
    prob += pulp.lpSum(objective)
    return deviation


def solve(prob, solver_name, time_limit, gap_rel, warm=False):
    """Solves prob; returns "optimal" (proven within gap_rel), "feasible" (time limit hit first) or "infeasible"."""
    prob.solve(make_solver(solver_name, time_limit, gap_rel, warm))
    if prob.sol_status == pulp.LpSolutionOptimal:
        return "optimal"
    if prob.sol_status == pulp.LpSolutionIntegerFeasible:
        return "feasible"
    return "infeasible"


def one_hot_servings(prob, keys, caps):
    """
    One binary per (key, serving count): z[key][k] = 1 means k servings. Returns (z, servings, used),
    where servings and used are expressions over z. Avoids y <= s <= cap*y linking constraints,
    which made the model ~3x slower.
    """
    z, servings, used = {}, {}, {}
    for n, key in enumerate(keys):
        z[key] = {k: prob.add_variable(f"z_{n}_{k}", cat="Binary") for k in range(1, caps[key] + 1)}
        if len(z[key]) > 1:
            prob += pulp.lpSum(z[key].values()) <= 1
        servings[key] = pulp.lpSum(k * v for k, v in z[key].items())
        used[key] = pulp.lpSum(z[key].values())
    return z, servings, used


def chosen_servings(keys, servings):
    """{key: servings} for every key the solved model actually uses."""
    chosen = {}
    for key in keys:
        count = int(round(pulp.value(servings[key]) or 0))
        if count > 0:
            chosen[key] = count
    return chosen


def optimize_meal_plan(foods, target_calories, target_protein, target_carbs, target_fat,
                       restaurant=None, restaurant_meal=None, time_limit=10, gap_rel=0.005,
                       solver_name=None, warm_start_iterations=2000, locked=None, excluded=None):
    """
    Finds the meal plan with the lowest solver.py penalty as an integer program (HiGHS or CBC via PuLP).

    locked is a list of {"name", "meal", "servings"} that must appear exactly as given; their
    serving variables are fixed before solving. excluded is a list of food names that must not
    appear anywhere. Locks are checked against meal slots, locations, categories, serving caps
    and the meal structure first; a conflict returns status "infeasible" with a "reason".

    Uses the same plan structure as solver.build_meal_plan, but fiber <= 35g is a hard
    constraint instead of a penalty. solver_name is "highs" or "cbc"; by default HiGHS is
    used when highspy is installed, otherwise CBC. With HiGHS, a seeded heuristic run of
    warm_start_iterations (0 to disable) provides the starting plan.

    Returns solver.run_heuristic_solver's dict shape plus "status" ("optimal" if proven
    within gap_rel of the best possible penalty, "feasible" if the time limit hit first,
    or "infeasible" if no valid plan exists or none was found in time), "solve_time" in
    seconds and "solver". Infeasible results have no items, None for macros and penalty, and a
    "reason" explaining why.
    """
    start = time.perf_counter()
    solver_name = solver_name or default_solver()
    locked, excluded = list(locked or []), set(excluded or [])
    foods = [f for f in foods if f["name"] not in excluded]

    reason = lock_conflict(foods, locked, excluded, restaurant, restaurant_meal)
    pairs = eligible_pairs(foods, restaurant, restaurant_meal)
    reason = reason or missing_pool(foods, pairs)
    if reason:
        return infeasible_result(time.perf_counter() - start, solver_name, reason)

    targets = {"calories": target_calories, "protein": target_protein, "carbs": target_carbs, "fat": target_fat}
    prob = pulp.LpProblem("meal_plan", pulp.LpMinimize)

    # z[f, m][k] = 1 means k servings of food f in meal m
    z, s, y = one_hot_servings(prob, pairs, {(i, m): serving_cap(foods[i], m) for i, m in pairs})

    def used(meal, category=None):
        return pulp.lpSum(y[i, m] for (i, m) in pairs
                          if m == meal and (category is None or foods[i]["category"] == category))

    for meal in MAIN_MEALS:
        prob += used(meal, "staple") == 1
        prob += used(meal, "lean_protein") == 1
    prob += used("Snack") >= 1
    prob += used("Snack") <= 2

    # Each food at most once per day (by name, like pick_unique). This also keeps
    # dinner's staple different from lunch's. Foods with a single possible placement
    # can't repeat, so they need no constraint.
    pairs_by_name = {}
    for pair in pairs:
        pairs_by_name.setdefault(foods[pair[0]]["name"], []).append(pair)
    for name_pairs in pairs_by_name.values():
        if len(name_pairs) > 1:
            prob += pulp.lpSum(y[p] for p in name_pairs) <= 1

    def total(key):
        return pulp.lpSum(foods[i][key] * s[i, m] for (i, m) in pairs)

    prob += total("fiber") <= MAX_FIBER

    deviation = add_deviation_objective(prob, {m: total(m) for m in MACROS}, targets,
                                        {m: total_range(foods, pairs, m) for m in MACROS})

    # Fix each locked placement: exactly that serving count of that food in that meal
    index = {f["name"]: i for i, f in enumerate(foods)}
    for lock in locked:
        var = z[index[lock["name"]], lock["meal"]][lock["servings"]]
        var.lowBound = var.upBound = 1

    # Warm start only helps HiGHS (2.9s -> 2.4s); it made CBC slightly slower, so CBC skips it.
    # A heuristic plan that breaks a lock would be rejected as a start, so only matching ones are used.
    warm = False
    if solver_name == "highs" and warm_start_iterations:
        plan = heuristic_start(foods, targets, restaurant, restaurant_meal, warm_start_iterations)
        warm = (plan is not None and plan_has_locks(plan, locked)
                and set_initial_values(foods, pairs, plan, z, deviation, targets))

    status = solve(prob, solver_name, time_limit, gap_rel, warm)
    solve_time = time.perf_counter() - start
    if status == "infeasible":
        if locked:
            reason = ("No plan can complete the meal structure around the locked foods with the remaining "
                      "foods (for example, a lock may use up the only option another meal needs)")
        elif excluded:
            reason = "No plan fits the meal structure (fiber at most 35g) with the foods left after the exclusions"
        else:
            reason = "No plan fits the meal structure (fiber at most 35g) with the current foods"
        return infeasible_result(solve_time, solver_name, reason)

    servings = chosen_servings(pairs, s)
    result = build_result(foods, servings, target_calories, target_protein, target_carbs, target_fat)
    result["status"] = status
    result["solve_time"] = solve_time
    result["solver"] = solver_name
    return result


def set_initial_values(foods, pairs, plan, z, deviation, targets):
    """Loads a solver.py plan into the variables' initial values. Returns False if it doesn't fit the model."""
    servings = {}
    for item in plan["items"]:
        match = [(i, m) for (i, m) in pairs if m == item["meal"] and foods[i]["name"] == item["name"]]
        if not match or item["servings"] not in z[match[0]]:
            return False
        servings[match[0]] = item["servings"]

    for key in pairs:
        for k, var in z[key].items():
            var.setInitialValue(1 if servings.get(key) == k else 0)
    for macro, (over, under) in deviation.items():
        diff = sum(foods[i][macro] * count for (i, _), count in servings.items()) - targets[macro]
        over.setInitialValue(max(0, diff))
        under.setInitialValue(max(0, -diff))
    return True


# --- Restaurant orders -------------------------------------------------------

# Structure rules come from solver.py so the rules-following heuristic baseline matches exactly
COMPONENT_LIMITS = solver.ORDER_COMPONENT_LIMITS
EXTRAS = solver.ORDER_EXTRAS
MAX_EXTRAS = solver.ORDER_MAX_EXTRAS
order_serving_cap = solver.order_serving_cap
# Display order of an order's items
COMPONENT_ORDER = ["base", "protein", "beans", "topping", "sauce"]


def order_total_range(foods, items, macro):
    """Lowest and highest possible total of a macro for one order, given the component limits."""
    low = high = 0.0
    for component, (min_count, max_count) in COMPONENT_LIMITS.items():
        values = sorted(foods[i][macro] for i in items if foods[i]["component_type"] == component)
        doubled = sorted(foods[i][macro] * order_serving_cap(foods[i])
                         for i in items if foods[i]["component_type"] == component)
        low += sum(values[:min_count])
        high += sum(doubled[-max_count:]) if max_count else 0
    extras = sorted(foods[i][macro] for i in items if foods[i]["component_type"] in EXTRAS)
    high += sum(extras[-MAX_EXTRAS:])
    return low, high


def optimize_restaurant_order(foods, target_calories, target_protein, target_carbs, target_fat,
                              time_limit=1, gap_rel=0.005, solver_name=None):
    """
    Builds the single restaurant order with the lowest solver.order_penalty, as an integer program.

    foods is one restaurant's menu (items without a component_type are ignored). An order has
    1-2 bases and 1-2 proteins (1-2 servings each), at most 1 beans, and at most 4 toppings and
    sauces combined (1 serving each); each item appears at most once. Returns
    solver.run_restaurant_solver's dict shape plus "status", "solve_time" and "solver",
    with the same meaning as in optimize_meal_plan.
    """
    start = time.perf_counter()
    solver_name = solver_name or default_solver()
    items = [i for i, f in enumerate(foods) if f.get("component_type") in COMPONENT_ORDER]

    def of_type(*components):
        return [i for i in items if foods[i]["component_type"] in components]

    if any(len(of_type(c)) < min_count for c, (min_count, _) in COMPONENT_LIMITS.items()):
        return infeasible_result(time.perf_counter() - start, solver_name)

    targets = {"calories": target_calories, "protein": target_protein, "carbs": target_carbs, "fat": target_fat}
    prob = pulp.LpProblem("restaurant_order", pulp.LpMinimize)

    # z[i][k] = 1 means k servings of item i; one variable group per item, so each is used at most once
    _, s, y = one_hot_servings(prob, items, {i: order_serving_cap(foods[i]) for i in items})

    for component, (min_count, max_count) in COMPONENT_LIMITS.items():
        count = pulp.lpSum(y[i] for i in of_type(component))
        if min_count:
            prob += count >= min_count
        prob += count <= max_count
    prob += pulp.lpSum(y[i] for i in of_type(*EXTRAS)) <= MAX_EXTRAS

    totals = {m: pulp.lpSum(foods[i][m] * s[i] for i in items) for m in MACROS}
    add_deviation_objective(prob, totals, targets, {m: order_total_range(foods, items, m) for m in MACROS})

    status = solve(prob, solver_name, time_limit, gap_rel)
    solve_time = time.perf_counter() - start
    if status == "infeasible":
        return infeasible_result(solve_time, solver_name)

    servings = chosen_servings(items, s)
    result_items = []
    order_totals = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}
    for i in sorted(servings, key=lambda i: (COMPONENT_ORDER.index(foods[i]["component_type"]), i)):
        food, count = foods[i], servings[i]
        for key in order_totals:
            order_totals[key] += food[key] * count
        result_items.append({"name": food["name"], "servings": count, "category": food["category"], "meal": "Order"})

    penalty = solver.order_penalty(order_totals, target_calories, target_protein, target_carbs, target_fat)
    order_totals["fiber"] = round(order_totals["fiber"], 1)
    return {"items": result_items, "macros": order_totals, "penalty": penalty,
            "status": status, "solve_time": solve_time, "solver": solver_name}
