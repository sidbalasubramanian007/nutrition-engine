"""
API tests with FastAPI's TestClient.

Foods come from the data files (setup_db.collect_products) via a dependency override, so the
foods/optimize tests need no database. Save/list/get use test_schema's temporary database
fixtures and are skipped like those when no test database is configured.
"""
import contextlib
import io

import pytest
from fastapi.testclient import TestClient

import calculator
import db
import setup_db
import solver
from api import main
from test_schema import PLAN_FOODS, TARGETS, conn, insert, plan_conn, temp_db  # noqa: F401 (fixtures)

DEFAULT_TARGETS = {"calories": 2800, "protein": 170, "carbs": 390, "fat": 68}


def file_foods():
    with contextlib.redirect_stdout(io.StringIO()):
        return setup_db.collect_products(with_seeds=True, with_trader_joes=True)


@pytest.fixture
def client():
    foods = file_foods()
    main.app.dependency_overrides[main.load_foods] = lambda: foods
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


# --- health ---

class FakeConnection:
    def cursor(self):
        return contextlib.nullcontext(type("Cursor", (), {"execute": lambda self, sql: None})())

    def close(self):
        pass


def test_health_reports_database_up(client, monkeypatch):
    monkeypatch.setattr(db, "get_connection", lambda: FakeConnection())
    assert client.get("/api/health").json() == {"status": "ok", "db": True}


def test_health_reports_database_down_without_failing(client, monkeypatch):
    def refuse():
        raise OSError("connection refused")
    monkeypatch.setattr(db, "get_connection", refuse)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": False}


# --- foods ---

def test_foods_filter_by_location_and_source(client):
    cava = client.get("/api/foods", params={"location": "CAVA"}).json()
    assert cava and {f["location"] for f in cava} == {"CAVA"}
    assert {"name", "calories", "protein", "carbs", "fat", "fiber", "category", "meal_slots", "source"} <= set(cava[0])

    grocery = client.get("/api/foods", params={"location": "Grocery"}).json()
    no_estimates = client.get("/api/foods", params={"location": "Grocery", "exclude_estimated": True}).json()
    assert any(f["source"] == "gemini_estimate" for f in grocery)
    assert no_estimates and all(f["source"] != "gemini_estimate" for f in no_estimates)


def test_unknown_location_has_no_foods(client):
    response = client.get("/api/foods", params={"location": "Taco Bell"})
    assert response.status_code == 200 and response.json() == []


def test_new_restaurants_work_without_code_changes(client):
    # Restaurants come from the data: add a menu with the same structure and it can be optimized
    foods = file_foods()
    taqueria = [dict(f, name=f["name"].replace("Chipotle", "Taqueria"), location="Taqueria")
                for f in foods if f["location"] == "Chipotle"]
    main.app.dependency_overrides[main.load_foods] = lambda: foods + taqueria
    order = client.post("/api/restaurant/optimize", json={
        "restaurant": "Taqueria", "targets": {"calories": 900, "protein": 60, "carbs": 100, "fat": 30}}).json()
    assert order["status"] == "optimal"
    assert all(i["name"].startswith("Taqueria") for i in order["meals"][0]["items"])


@pytest.mark.parametrize("restaurant", ["Taco Bell", "Grocery"])
def test_unknown_restaurant_is_422_with_the_known_ones(client, restaurant):
    response = client.post("/api/restaurant/optimize", json={
        "restaurant": restaurant, "targets": {"calories": 900, "protein": 60, "carbs": 100, "fat": 30}})
    assert response.status_code == 422
    assert "CAVA, Chipotle" in response.json()["detail"]


# --- targets ---

def test_calculate_targets_uses_calculator(client):
    body = {"age": 30, "weight_lbs": 180, "height_ft": 5, "height_in": 11, "gender": "Male",
            "activity": "Moderately Active", "goal": "Bulking"}
    calories = calculator.calculate_tdee(180, 5, 11, 30, "Male", "Moderately Active", "Bulking")
    protein = calculator.estimate_protein(180, "Bulking")
    fat, carbs = calculator.estimate_fat_and_carbs(calories, protein)

    response = client.post("/api/targets/calculate", json=body)

    assert response.status_code == 200
    assert response.json() == {"calories": calories, "protein": protein, "carbs": carbs, "fat": fat}


# --- optimize ---

def test_optimize_returns_a_structured_plan(client):
    response = client.post("/api/plans/optimize", json={"targets": DEFAULT_TARGETS, "time_limit": 2})
    assert response.status_code == 200
    plan = response.json()

    assert plan["status"] in ("optimal", "feasible")
    assert plan["solver"] in ("highs", "cbc") and plan["solve_time"] > 0
    assert [m["name"] for m in plan["meals"]] == ["Breakfast", "Lunch", "Dinner", "Snack"]
    for meal in plan["meals"][:3]:
        assert sorted(i["category"] for i in meal["items"]) == ["lean_protein", "staple"]
    assert 1 <= len(plan["meals"][3]["items"]) <= 2

    items = [i for m in plan["meals"] for i in m["items"]]
    for key in ("calories", "protein", "carbs", "fat"):
        assert plan["macros"][key] == pytest.approx(sum(i["macros"][key] for i in items), abs=0.5)
    totals = dict(plan["macros"], fiber=0)  # fiber <= 35 is a hard constraint, so its penalty term is 0
    assert plan["penalty"] == pytest.approx(solver.plan_penalty(totals, **{f"target_{k}": v for k, v in DEFAULT_TARGETS.items()}))


def test_optimize_can_exclude_estimated_foods(client):
    estimated = {f["name"] for f in file_foods() if f["source"] == "gemini_estimate"}
    plan = client.post("/api/plans/optimize", json={"targets": DEFAULT_TARGETS, "exclude_estimated": True}).json()
    assert plan["status"] in ("optimal", "feasible")
    assert not {i["name"] for m in plan["meals"] for i in m["items"]} & estimated


def test_infeasible_plan_is_200_with_status_and_message(client):
    no_proteins = [f for f in file_foods() if f["category"] != "lean_protein"]
    main.app.dependency_overrides[main.load_foods] = lambda: no_proteins

    response = client.post("/api/plans/optimize", json={"targets": DEFAULT_TARGETS})

    assert response.status_code == 200
    plan = response.json()
    assert plan["status"] == "infeasible"
    assert plan["meals"] == [] and plan["macros"] is None and plan["penalty"] is None
    assert plan["message"] == "No lean protein is available for Breakfast with the current foods"


@pytest.mark.parametrize("restaurant", ["Chipotle", "CAVA"])
def test_restaurant_order_has_the_same_shape(client, restaurant):
    targets = {"calories": 900, "protein": 60, "carbs": 100, "fat": 30}
    order = client.post("/api/restaurant/optimize", json={"restaurant": restaurant, "targets": targets}).json()

    assert order["status"] == "optimal"
    assert [m["name"] for m in order["meals"]] == ["Order"]
    assert all(i["name"].startswith(restaurant) for i in order["meals"][0]["items"])
    assert order["penalty"] == pytest.approx(solver.order_penalty(order["macros"], 900, 60, 100, 30))


# --- invalid input -> 422 ---

@pytest.mark.parametrize("path, body", [
    ("/api/plans/optimize", {"targets": dict(DEFAULT_TARGETS, calories=500)}),
    ("/api/plans/optimize", {"targets": dict(DEFAULT_TARGETS, calories=9000)}),
    ("/api/plans/optimize", {"targets": dict(DEFAULT_TARGETS, protein=-5)}),
    ("/api/plans/optimize", {"targets": DEFAULT_TARGETS, "time_limit": 6}),
    ("/api/plans/optimize", {"targets": DEFAULT_TARGETS, "time_limit": 0}),
    ("/api/plans/optimize", {"targets": {"calories": 2800}}),
    ("/api/plans/optimize", {"targets": DEFAULT_TARGETS, "time_limt": 2}),
    ("/api/restaurant/optimize", {"restaurant": "Taco Bell", "targets": {"calories": 900, "protein": 60, "carbs": 100, "fat": 30}}),
    ("/api/restaurant/optimize", {"restaurant": "CAVA", "targets": {"calories": 5000, "protein": 60, "carbs": 100, "fat": 30}}),
    ("/api/targets/calculate", {"age": 30, "weight_lbs": 180, "height_ft": 5, "height_in": 11, "gender": "Other",
                                "activity": "Sedentary", "goal": "Cutting"}),
    ("/api/targets/calculate", {"age": 5, "weight_lbs": 180, "height_ft": 5, "height_in": 11, "gender": "Male",
                                "activity": "Sedentary", "goal": "Cutting"}),
    ("/api/targets/calculate", {"age": 30, "weight_lbs": 180, "height_ft": 5, "height_in": 12, "gender": "Male",
                                "activity": "Sedentary", "goal": "Cutting"}),
])
def test_invalid_input_is_422(client, path, body):
    response = client.post(path, json=body)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]


def test_infeasible_or_restaurant_plans_cannot_be_saved(client):
    infeasible = {"status": "infeasible", "meals": [], "solve_time": 0.1, "solver": "highs"}
    assert client.post("/api/plans/save", json={"plan": infeasible, "targets": DEFAULT_TARGETS}).status_code == 422

    order = client.post("/api/restaurant/optimize", json={
        "restaurant": "CAVA", "targets": {"calories": 900, "protein": 60, "carbs": 100, "fat": 30}}).json()
    assert client.post("/api/plans/save", json={"plan": order, "targets": DEFAULT_TARGETS}).status_code == 422


# --- CORS ---

def test_cors_allows_the_configured_origin_only(client):
    def preflight(origin):
        return client.options("/api/plans/optimize", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST"})

    assert preflight("http://localhost:5173").headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in preflight("http://evil.example").headers


# --- save / list / get (temporary database) ---

def api_plan(**overrides):
    """A plan in the optimize endpoint's shape, using test_schema's PLAN_FOODS."""
    def item(name, servings, category):
        food = next(f for f in PLAN_FOODS if f["name"] == name)
        return {"name": name, "servings": servings, "category": category,
                "macros": {k: food[k] * servings for k in ("calories", "protein", "carbs", "fat", "fiber")}}
    plan = {
        "status": "optimal", "solve_time": 0.2, "solver": "highs", "penalty": 1234.5,
        "macros": {"calories": 900, "protein": 104, "carbs": 81, "fat": 16.8, "fiber": 11},
        "meals": [
            {"name": "Breakfast", "items": [item("Plan Oats", 2, "staple")]},
            {"name": "Dinner", "items": [item("Plan Chicken", 3, "lean_protein")]},
            {"name": "Snack", "items": [item("Plan Banana", 1, "carb")]},
        ],
    }
    plan.update(overrides)
    return plan


def test_save_list_and_get_round_trip(client, plan_conn):
    response = client.post("/api/plans/save", json={"plan": api_plan(), "targets": TARGETS})
    assert response.status_code == 200
    plan_id = response.json()["id"]

    listed = client.get("/api/plans").json()
    assert [p["id"] for p in listed] == [plan_id]
    assert listed[0]["item_count"] == 3
    assert listed[0]["macros"] == {"calories": 900, "protein": 104, "carbs": 81, "fat": 16.8, "fiber": 11}
    assert listed[0]["targets"] == TARGETS

    saved = client.get(f"/api/plans/{plan_id}").json()
    assert saved["id"] == plan_id and saved["status"] == "optimal" and saved["penalty"] == 1234.5
    assert [(m["name"], [(i["name"], i["servings"]) for i in m["items"]]) for m in saved["meals"]] == [
        ("Breakfast", [("Plan Oats", 2)]), ("Dinner", [("Plan Chicken", 3)]), ("Snack", [("Plan Banana", 1)])]
    assert saved["meals"][1]["items"][0]["macros"] == {"calories": 495, "protein": 93, "carbs": 0, "fat": 10.8, "fiber": 0}


def test_get_unknown_plan_is_404(client, plan_conn):
    assert client.get("/api/plans/999999").status_code == 404


def test_saving_a_plan_with_unknown_foods_is_422_and_saves_nothing(client, plan_conn):
    plan = api_plan()
    plan["meals"][0]["items"][0]["name"] = "Not A Product"
    response = client.post("/api/plans/save", json={"plan": plan, "targets": TARGETS})
    assert response.status_code == 422
    assert "Not A Product" in response.json()["detail"]
    assert client.get("/api/plans").json() == []



# --- locks and exclusions ---

def test_optimize_honours_locks_and_exclusions(client):
    body = {"targets": DEFAULT_TARGETS,
            "locked": [{"name": "Chicken Breast", "meal": "Dinner", "servings": 2}],
            "excluded": ["Jasmine Rice", "Whey Protein Powder"]}
    plan = client.post("/api/plans/optimize", json=body).json()

    assert plan["status"] in ("optimal", "feasible")
    dinner = next(m for m in plan["meals"] if m["name"] == "Dinner")
    assert {"name": "Chicken Breast", "servings": 2} in [{"name": i["name"], "servings": i["servings"]} for i in dinner["items"]]
    assert not {i["name"] for m in plan["meals"] for i in m["items"]} & {"Jasmine Rice", "Whey Protein Powder"}


def test_conflicting_lock_is_200_infeasible_with_the_reason(client):
    body = {"targets": DEFAULT_TARGETS, "locked": [{"name": "Chicken Breast", "meal": "Breakfast", "servings": 1}]}
    response = client.post("/api/plans/optimize", json=body)
    assert response.status_code == 200
    assert response.json()["status"] == "infeasible"
    assert response.json()["message"] == "'Chicken Breast' can't go in Breakfast: its meal slots are lunch, dinner"


@pytest.mark.parametrize("lock", [
    {"name": "Chicken Breast", "meal": "Brunch", "servings": 1},
    {"name": "Chicken Breast", "meal": "Dinner", "servings": 0},
    {"name": "Chicken Breast", "meal": "Dinner", "servings": 4},
    {"name": "", "meal": "Dinner", "servings": 1},
    {"name": "Chicken Breast", "meal": "Dinner"},
])
def test_malformed_lock_is_422(client, lock):
    assert client.post("/api/plans/optimize", json={"targets": DEFAULT_TARGETS, "locked": [lock]}).status_code == 422


def test_delete_plan_removes_it_and_its_items(client, plan_conn):
    keep = client.post("/api/plans/save", json={"plan": api_plan(), "targets": TARGETS}).json()["id"]
    remove = client.post("/api/plans/save", json={"plan": api_plan(), "targets": TARGETS}).json()["id"]

    response = client.delete(f"/api/plans/{remove}")
    assert response.status_code == 204 and response.content == b""

    assert client.get(f"/api/plans/{remove}").status_code == 404
    assert [p["id"] for p in client.get("/api/plans").json()] == [keep]
    with plan_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM plan_items WHERE plan_id = %s", (remove,))
        assert cur.fetchone()[0] == 0


def test_delete_unknown_plan_is_404(client, plan_conn):
    assert client.delete("/api/plans/999999").status_code == 404
