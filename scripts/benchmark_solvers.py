"""Benchmarks the heuristic solver against the MILP optimizer on random, realistic macro targets.

Usage (from the repo root; macOS has no `timeout`, the perl line is equivalent):
    timeout 1800 python scripts/benchmark_solvers.py
    perl -e 'alarm shift; exec @ARGV' 1800 python scripts/benchmark_solvers.py

Foods come straight from food_data.csv, data/*.csv and trader_joes_macros.json (no database),
merged with setup_db.py's rules, using the grocery pool. For each target it runs:
  - heuristic: solver.run_heuristic_solver, 50,000 iterations, seeded
  - milp_1s:   optimizer.optimize_meal_plan with time_limit=1 and default settings (what the app uses)
  - milp_30s:  time_limit=30 and gap_rel=0, to get the proven optimum and the time to prove it
Results are rewritten to benchmark_results.json (gitignored) after every target, so a
timeout still leaves everything finished so far.
"""
import contextlib
import io
import json
import os
import random
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import optimizer
import setup_db
import solver

SEED = 2026
NUM_TARGETS = 50
HEURISTIC_ITERATIONS = 50000
APP_TIME_LIMIT = 1
PROOF_TIME_LIMIT = 30
MIN_CARBS = 50  # targets whose leftover calories leave fewer carbs than this are redrawn
MACROS = ["calories", "protein", "carbs", "fat"]
METHODS = ["heuristic", "milp_1s", "milp_30s"]
RESULTS_PATH = os.path.join(ROOT, "benchmark_results.json")
TOLERANCE = 1e-6


def load_grocery_foods():
    with contextlib.redirect_stdout(io.StringIO()):
        foods = setup_db.collect_products(with_seeds=True, with_trader_joes=True)
    return [f for f in foods if f["location"] == "Grocery"]


def generate_targets(rng, count):
    """Calories 1600-3600; protein 0.7-1.2 g/lb of a 120-220 lb person; fat 20-35% of calories; rest carbs."""
    targets = []
    while len(targets) < count:
        bodyweight = rng.uniform(120, 220)
        calories = round(rng.uniform(1600, 3600))
        protein = round(bodyweight * rng.uniform(0.7, 1.2))
        fat = round(calories * rng.uniform(0.20, 0.35) / 9)
        carbs = round((calories - 4 * protein - 9 * fat) / 4)
        if carbs < MIN_CARBS:
            continue
        targets.append({"calories": calories, "protein": protein, "carbs": carbs, "fat": fat,
                        "bodyweight_lb": round(bodyweight, 1)})
    return targets


def summarize_plan(plan, target, wall_time, status):
    if plan is None or plan["penalty"] is None:
        return {"status": status, "penalty": None, "abs_error": None, "macros": None, "wall_time": wall_time}
    return {
        "status": status,
        "penalty": plan["penalty"],
        "abs_error": {m: abs(plan["macros"][m] - target[m]) for m in MACROS},
        "macros": plan["macros"],
        "wall_time": wall_time,
    }


def run_heuristic(foods, target, seed):
    random.seed(seed)
    start = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        plan = solver.run_heuristic_solver(foods, target["calories"], target["protein"], target["carbs"],
                                           target["fat"], iterations=HEURISTIC_ITERATIONS)
    wall_time = time.perf_counter() - start
    return summarize_plan(plan, target, wall_time, "found" if plan else "no_plan")


def run_milp(foods, target, **kwargs):
    start = time.perf_counter()
    plan = optimizer.optimize_meal_plan(foods, target["calories"], target["protein"], target["carbs"],
                                        target["fat"], **kwargs)
    wall_time = time.perf_counter() - start
    return summarize_plan(plan, target, wall_time, plan["status"])


def median(values):
    return statistics.median(values) if values else None


def mean(values):
    return statistics.mean(values) if values else None


def percent(numerator, denominator):
    return 100.0 * numerator / denominator if denominator else None


def summarize(results):
    summary = {"targets_run": len(results), "methods": {}}
    for method in METHODS:
        runs = [r[method] for r in results]
        with_plan = [run for run in runs if run["penalty"] is not None]
        summary["methods"][method] = {
            "plans_found": len(with_plan),
            "median_penalty": median([run["penalty"] for run in with_plan]),
            "mean_penalty": mean([run["penalty"] for run in with_plan]),
            "median_abs_error": {m: median([run["abs_error"][m] for run in with_plan]) for m in MACROS},
            "median_wall_time": median([run["wall_time"] for run in runs]),
            "statuses": {s: sum(run["status"] == s for run in runs) for s in sorted({run["status"] for run in runs})},
        }

    def penalty(r, method):
        return r[method]["penalty"]

    beats_heuristic = sum(
        penalty(r, "milp_1s") is not None and (penalty(r, "heuristic") is None
                                               or penalty(r, "milp_1s") <= penalty(r, "heuristic") + TOLERANCE)
        for r in results)
    proven = [r for r in results if r["milp_30s"]["status"] == "optimal"]
    matched = sum(penalty(r, "milp_1s") is not None
                  and penalty(r, "milp_1s") <= penalty(r, "milp_30s") + TOLERANCE for r in proven)
    summary["pct_milp_1s_le_heuristic"] = percent(beats_heuristic, len(results))
    summary["pct_milp_1s_matched_proven_optimum"] = percent(matched, len(proven))
    summary["matched_denominator"] = len(proven)
    summary["pct_proven_optimal_within_30s"] = percent(len(proven), len(results))
    summary["median_time_to_prove"] = median([r["milp_30s"]["wall_time"] for r in proven])
    return summary


def write_results(foods, targets, results):
    payload = {
        "config": {"seed": SEED, "num_targets": NUM_TARGETS, "heuristic_iterations": HEURISTIC_ITERATIONS,
                   "app_time_limit": APP_TIME_LIMIT, "proof_time_limit": PROOF_TIME_LIMIT,
                   "min_carbs": MIN_CARBS, "pool_size": len(foods), "solver": optimizer.default_solver()},
        "targets": targets,
        "results": results,
        "summary": summarize(results),
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    return payload["summary"]


def fmt(value, spec=".1f", none="-"):
    return none if value is None else format(value, spec)


def describe(run):
    return f"{fmt(run['penalty'], '8.1f', '       -')} {run['status']:<10} {run['wall_time']:5.2f}s"


def print_summary(summary):
    print("\n=== Summary ===")
    print(f"{'method':<11}{'plans':>6}{'median pen':>12}{'mean pen':>11}"
          + "".join(f"{'err ' + m[:4]:>10}" for m in MACROS) + f"{'med time':>10}")
    for method in METHODS:
        s = summary["methods"][method]
        print(f"{method:<11}{s['plans_found']:>6}{fmt(s['median_penalty']):>12}{fmt(s['mean_penalty']):>11}"
              + "".join(f"{fmt(s['median_abs_error'][m]):>10}" for m in MACROS)
              + f"{fmt(s['median_wall_time'], '.2f'):>9}s")
    print(f"\nMILP@1s penalty <= heuristic:        {fmt(summary['pct_milp_1s_le_heuristic'])}% of targets")
    print(f"MILP@1s matched the proven optimum:   {fmt(summary['pct_milp_1s_matched_proven_optimum'])}% "
          f"(of the {summary['matched_denominator']} targets proven optimal)")
    print(f"Proven optimal within 30s:            {fmt(summary['pct_proven_optimal_within_30s'])}% of targets "
          f"(median time to prove {fmt(summary['median_time_to_prove'], '.2f')}s)")
    print(f"Statuses: " + "; ".join(f"{m}: {summary['methods'][m]['statuses']}" for m in METHODS))
    print(f"\nWrote {os.path.relpath(RESULTS_PATH, ROOT)}")


def main():
    foods = load_grocery_foods()
    targets = generate_targets(random.Random(SEED), NUM_TARGETS)
    print(f"Grocery pool: {len(foods)} foods. {NUM_TARGETS} targets, seed {SEED}. "
          f"MILP solver: {optimizer.default_solver()}.", flush=True)

    results, summary = [], None
    for n, target in enumerate(targets, start=1):
        result = {
            "target": target,
            "heuristic": run_heuristic(foods, target, seed=SEED + n),
            "milp_1s": run_milp(foods, target, time_limit=APP_TIME_LIMIT),
            "milp_30s": run_milp(foods, target, time_limit=PROOF_TIME_LIMIT, gap_rel=0),
        }
        results.append(result)
        summary = write_results(foods, targets, results)
        print(f"[{n:2}/{NUM_TARGETS}] target {target['calories']:4}kcal {target['protein']:3}P "
              f"{target['carbs']:3}C {target['fat']:3}F | heuristic {describe(result['heuristic'])} | "
              f"MILP@1s {describe(result['milp_1s'])} | MILP@30s {describe(result['milp_30s'])}", flush=True)

    print_summary(summary)


if __name__ == "__main__":
    main()
