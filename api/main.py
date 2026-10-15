"""
HTTP API over the existing modules (optimizer, solver, calculator, db); no logic is duplicated here.

Run from the repo root:
    uvicorn api.main:app --reload
CORS origins come from ALLOWED_ORIGINS (comma-separated, default http://localhost:5173).
"""
import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

import calculator
import db  # loads .env, so ALLOWED_ORIGINS can live there too
import optimizer
import solver
from api.models import (Food, Health, Macros, MealGroup, Plan, PlanItem, PlanRequest, RestaurantRequest,
                        SavedPlan, SavedPlanSummary, SavePlanRequest, SavePlanResponse, Targets, TargetsRequest,
                        TargetsResponse)

log = logging.getLogger("api")

MACRO_KEYS = ["calories", "protein", "carbs", "fat", "fiber"]
INFEASIBLE_PLAN = ("No meal plan fits the meal structure (a staple and a protein at breakfast, lunch and dinner, "
                   "plus a snack, with fiber under 35g) using the foods available. Load more foods or widen the targets.")
INFEASIBLE_ORDER = ("No order fits the order structure (1-2 bases, 1-2 proteins, at most 1 beans, at most 4 toppings "
                    "and sauces) with this restaurant's menu.")

app = FastAPI(title="Nutrition Engine API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


def unavailable(message):
    """503 for database failures. Details (which can include hosts or usernames) go to the log, not the client."""
    log.exception(message)
    return HTTPException(status_code=503, detail=message)


def load_foods():
    """All products from the database, in the solver's food shape. Overridden in tests."""
    try:
        return solver.rows_to_foods(solver.fetch_products_rows())
    except Exception:
        raise unavailable("Database unavailable")


def without_estimates(foods, exclude_estimated):
    return [f for f in foods if not (exclude_estimated and f["source"] == "gemini_estimate")]


def to_plan(result, foods, infeasible_message):
    """optimizer result -> Plan, with items grouped by meal and per-item macros."""
    if result["status"] == "infeasible":
        return Plan(status="infeasible", meals=[], solve_time=result["solve_time"], solver=result["solver"],
                    message=result.get("reason") or infeasible_message)
    by_name = {f["name"]: f for f in foods}
    return Plan(
        status=result["status"],
        meals=group_items(result["items"], by_name),
        macros=Macros(**result["macros"]),
        penalty=result["penalty"],
        solve_time=result["solve_time"],
        solver=result["solver"],
    )


def group_items(items, foods_by_name):
    """[{name, servings, category, meal}] -> MealGroups in first-seen meal order."""
    groups = {}
    for item in items:
        food = foods_by_name[item["name"]]
        groups.setdefault(item["meal"], []).append(PlanItem(
            name=item["name"], servings=item["servings"], category=item["category"],
            macros=Macros(**{k: round(food[k] * item["servings"], 1) for k in MACRO_KEYS}),
        ))
    return [MealGroup(name=meal, items=group) for meal, group in groups.items()]


# --- endpoints ---

@app.get("/api/health", response_model=Health)
def health():
    try:
        conn = db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
        finally:
            conn.close()
        return Health(status="ok", db=True)
    except Exception:
        return Health(status="ok", db=False)


@app.get("/api/foods", response_model=list[Food])
def list_foods(location: str | None = Query(None, description="Only foods from this location (Grocery or a restaurant)"),
               exclude_estimated: bool = False, foods: list = Depends(load_foods)):
    foods = without_estimates(foods, exclude_estimated)
    return [Food(**f) for f in foods if location is None or f["location"] == location]


@app.post("/api/targets/calculate", response_model=TargetsResponse)
def calculate_targets(body: TargetsRequest):
    calories = calculator.calculate_tdee(body.weight_lbs, body.height_ft, body.height_in, body.age,
                                         body.gender, body.activity, body.goal)
    protein = calculator.estimate_protein(body.weight_lbs, body.goal)
    fat, carbs = calculator.estimate_fat_and_carbs(calories, protein)
    return TargetsResponse(calories=calories, protein=protein, carbs=carbs, fat=fat)


@app.post("/api/plans/optimize", response_model=Plan)
def optimize_plan(body: PlanRequest, foods: list = Depends(load_foods)):
    pool = [f for f in without_estimates(foods, body.exclude_estimated) if f["location"] == "Grocery"]
    t = body.targets
    result = optimizer.optimize_meal_plan(pool, t.calories, t.protein, t.carbs, t.fat, time_limit=body.time_limit,
                                          locked=[lock.model_dump() for lock in body.locked],
                                          excluded=body.excluded)
    return to_plan(result, pool, INFEASIBLE_PLAN)


@app.post("/api/restaurant/optimize", response_model=Plan)
def optimize_restaurant(body: RestaurantRequest, foods: list = Depends(load_foods)):
    menu = [f for f in foods if f["location"] == body.restaurant]
    if body.restaurant == "Grocery" or not menu:
        restaurants = sorted({f["location"] for f in foods} - {"Grocery"})
        raise HTTPException(status_code=422, detail=f"Unknown restaurant {body.restaurant!r}; "
                                                    f"menus are loaded for {', '.join(restaurants) or 'none'}")
    t = body.targets
    result = optimizer.optimize_restaurant_order(menu, t.calories, t.protein, t.carbs, t.fat)
    return to_plan(result, menu, INFEASIBLE_ORDER)


@app.post("/api/plans/save", response_model=SavePlanResponse)
def save_plan(body: SavePlanRequest):
    plan = {
        "items": [{"name": item.name, "servings": item.servings, "category": item.category, "meal": meal.name}
                  for meal in body.plan.meals for item in meal.items],
        "penalty": body.plan.penalty,
        "status": body.plan.status,
        "solver": body.plan.solver,
    }
    targets = body.targets.model_dump()
    try:
        return SavePlanResponse(id=db.save_plan(plan, targets))
    except LookupError as e:  # a plan item isn't in products
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise unavailable("Could not save the plan")


@app.get("/api/plans", response_model=list[SavedPlanSummary])
def list_saved_plans(limit: int = Query(20, ge=1, le=100)):
    try:
        plans = db.list_plans(limit=limit)
    except Exception:
        raise unavailable("Could not load saved plans")
    return [SavedPlanSummary(**p) for p in plans]


@app.get("/api/plans/{plan_id}", response_model=SavedPlan)
def get_saved_plan(plan_id: int):
    try:
        plan = db.get_plan(plan_id)
    except Exception:
        raise unavailable("Could not load the plan")
    if plan is None:
        raise HTTPException(status_code=404, detail=f"No saved plan {plan_id}")
    by_name = {item["name"]: item for item in plan["items"]}
    return SavedPlan(
        id=plan["id"], created_at=plan["created_at"], targets=Targets(**plan["targets"]),
        meals=group_items(plan["items"], by_name), macros=Macros(**plan["macros"]),
        penalty=plan["penalty"], status=plan["status"], solver=plan["solver"],
    )


@app.delete("/api/plans/{plan_id}", status_code=204, response_class=Response)
def delete_saved_plan(plan_id: int):
    """Deletes a saved plan and its items. 204 on success, 404 if it doesn't exist."""
    try:
        deleted = db.delete_plan(plan_id)
    except Exception:
        raise unavailable("Could not delete the plan")
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No saved plan {plan_id}")
    return Response(status_code=204)
