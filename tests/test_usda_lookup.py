"""usda_lookup.py's parsing, scaling, client and review loop, with fixture JSON (no network)."""
import csv
import json
import os

import pytest

import usda_lookup

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
OATS = {"name": "Rolled Oats", "calories": 150, "protein": 5, "carbs": 27, "fat": 2.5, "fiber": 4}


def fixture(name):
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)


# --- per-100 g foods (Foundation / SR Legacy) ---

def test_foundation_energy_prefers_atwater_general_and_fiber_falls_back_to_aoac_total():
    # Like the real record: no 208 energy (only 957/958 and kJ) and no 291 fiber (only 293)
    values = usda_lookup.per_100g_values(fixture("usda_foundation_oats.json"))
    assert values == {"calories": 383, "protein": 13.2, "carbs": 67.9, "fat": 6.5, "fiber": 10.1}


def test_per_100g_values_scale_to_the_serving_weight():
    food = fixture("usda_foundation_oats.json")
    values, grams = usda_lookup.candidate_values(food, grams=40)
    # 40 g = 0.4 x the per-100 g values, rounded to 0.1
    assert grams == 40
    assert values == {"calories": 153.2, "protein": 5.3, "carbs": 27.2, "fat": 2.6, "fiber": 4.0}


def test_sr_legacy_uses_standard_energy_and_scales():
    food = fixture("usda_sr_legacy_chicken.json")
    values, _ = usda_lookup.candidate_values(food, grams=120)
    assert values == {"calories": 198.0, "protein": 37.2, "carbs": 0.0, "fat": 4.3, "fiber": 0.0}


def test_scale_keeps_missing_nutrients_missing():
    assert usda_lookup.scale({"calories": 200, "fiber": None}, 50) == {"calories": 100.0, "fiber": None}


@pytest.mark.parametrize("name, expected", [
    ("usda_foundation_oats.json", (40.0, "0.5 cup")),
    ("usda_sr_legacy_chicken.json", (140.0, "1 cup, chopped or diced")),
    ("usda_branded_muffins.json", None),
])
def test_serving_suggestion_comes_from_the_first_food_portion(name, expected):
    assert usda_lookup.suggest_serving(fixture(name)) == expected


def test_abridged_search_format_nutrients_are_read_too():
    hit = {"foodNutrients": [{"nutrientNumber": "203", "value": 20.5}, {"nutrientNumber": "208", "value": 120}]}
    assert usda_lookup.nutrient_amount(hit, ["203"]) == 20.5
    assert usda_lookup.nutrient_amount(hit, ["208"]) == 120


# --- Branded foods (per labelled serving) ---

def test_branded_uses_label_nutrients_per_serving_and_falls_back_for_missing_fiber():
    values, grams = usda_lookup.candidate_values(fixture("usda_branded_muffins.json"))
    # labelNutrients has no fiber: 1.8 g per 100 g x 113 g serving = 2.0
    assert grams == 113
    assert values == {"calories": 450, "protein": 6, "carbs": 60, "fat": 21, "fiber": 2.0}


def test_branded_serving_in_millilitres_has_no_gram_fallback():
    values, grams = usda_lookup.candidate_values(fixture("usda_branded_drink_ml.json"))
    assert grams is None
    assert values == {"calories": 160, "protein": 30, "carbs": 6, "fat": 3, "fiber": None}
    assert usda_lookup.is_complete(values)


# --- HTTP client: retries and key handling ---

class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.urls = []

    def post(self, url, json=None, timeout=None):
        self.urls.append(url)
        return self.responses.pop(0)


def test_client_waits_and_retries_on_rate_limit():
    session = FakeSession([FakeResponse(429, headers={"Retry-After": "3"}),
                           FakeResponse(429),
                           FakeResponse(200, {"foods": [{"fdcId": 1}]})])
    sleeps = []
    client = usda_lookup.FdcClient("SECRET-KEY", session=session, sleep=sleeps.append)

    assert client.search("oats", ["Foundation"]) == [{"fdcId": 1}]
    assert sleeps == [3.0, 2]  # Retry-After honored, then exponential backoff
    assert session.headers["X-Api-Key"] == "SECRET-KEY"
    assert all("SECRET-KEY" not in url for url in session.urls)


def test_client_gives_up_after_max_retries_without_leaking_the_key(capsys):
    session = FakeSession([FakeResponse(429)] * 3 + [FakeResponse(429, {"error": "slow down SECRET-KEY"})])
    client = usda_lookup.FdcClient("SECRET-KEY", session=session, sleep=lambda s: None, max_retries=3)

    with pytest.raises(usda_lookup.FdcError) as excinfo:
        client.search("oats", ["Foundation"])
    assert "429" in str(excinfo.value)
    assert "SECRET-KEY" not in str(excinfo.value)
    assert "SECRET-KEY" not in capsys.readouterr().out


def test_client_reports_auth_errors_with_a_hint():
    client = usda_lookup.FdcClient("BAD", session=FakeSession([FakeResponse(403, {"error": "API_KEY_INVALID"})]))
    with pytest.raises(usda_lookup.FdcError, match="check USDA_API_KEY"):
        client.details([1])


# --- review loop and overrides file ---

class FakeClient:
    def __init__(self, foods):
        self.foods = foods

    def search(self, query, data_types, require_all_words=False):
        self.query = (query, tuple(data_types), require_all_words)
        return [{"fdcId": f["fdcId"]} for f in self.foods]

    def details(self, fdc_ids):
        return {f["fdcId"]: f for f in self.foods}


def scripted(*answers):
    answers = list(answers)
    return lambda prompt: answers.pop(0)


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_accepting_a_per_100g_candidate_writes_scaled_values(tmp_path):
    path = tmp_path / "usda_overrides.csv"
    client = FakeClient([fixture("usda_foundation_oats.json")])

    # Enter accepts the suggested 40 g serving, then y accepts
    assert usda_lookup.review_product(client, OATS, False, str(path), dry_run=False, ask=scripted("", "y"))

    assert client.query == ("Rolled Oats", ("Foundation", "SR Legacy"), False)
    assert read_rows(path) == [{"Name": "Rolled Oats", "Calories": "153.2", "Protein": "5.3", "Carbs": "27.2",
                                "Fat": "2.6", "Fiber": "4", "Fdc_Id": "2346396", "Serving_Grams": "40"}]
    assert usda_lookup.override_names(str(path)) == {"Rolled Oats"}


def test_picking_another_candidate_and_skipping_writes_nothing(tmp_path):
    path = tmp_path / "usda_overrides.csv"
    client = FakeClient([fixture("usda_foundation_oats.json"), fixture("usda_sr_legacy_chicken.json")])

    assert usda_lookup.review_product(client, OATS, False, str(path), dry_run=False,
                                      ask=scripted("50", "2", "100", "n"))
    assert not path.exists()


def test_trader_joes_items_search_branded_and_dry_run_never_prompts_or_writes(tmp_path, capsys):
    path = tmp_path / "usda_overrides.csv"
    client = FakeClient([fixture("usda_branded_muffins.json")])
    muffins = {"name": "Lemon Poppy Seed Muffins", "calories": 450, "protein": 5, "carbs": 63, "fat": 20, "fiber": 1}

    def no_prompts(prompt):
        raise AssertionError("dry run asked a question")

    assert usda_lookup.review_product(client, muffins, True, str(path), dry_run=True, ask=no_prompts)
    assert client.query == ("Trader Joe's Lemon Poppy Seed Muffins", ("Branded",), True)
    assert not path.exists()
    out = capsys.readouterr().out
    assert "LEMON POPPY SEED MUFFINS (Trader Joe's)" in out
    assert "fdcId 1987654 · Branded" in out


def test_quitting_stops_the_review(tmp_path):
    client = FakeClient([fixture("usda_branded_muffins.json")])
    assert usda_lookup.review_product(client, OATS, True, str(tmp_path / "o.csv"), dry_run=False,
                                      ask=scripted("q")) is False


def test_search_sends_require_all_words_only_when_asked():
    session = FakeSession([FakeResponse(200, {"foods": []}), FakeResponse(200, {"foods": []})])
    payloads = []
    session.post = lambda url, json=None, timeout=None: (payloads.append(json), FakeResponse(200, {"foods": []}))[1]
    client = usda_lookup.FdcClient("KEY", session=session)
    client.search("Trader Joe's Muffins", ["Branded"], require_all_words=True)
    client.search("Rolled Oats", ["Foundation", "SR Legacy"])
    assert payloads[0]["requireAllWords"] is True
    assert "requireAllWords" not in payloads[1]


def test_no_match_is_reported_and_nothing_written(tmp_path, capsys):
    client = FakeClient([])
    assert usda_lookup.review_product(client, OATS, True, str(tmp_path / "o.csv"), dry_run=False, ask=scripted())
    assert "No USDA match" in capsys.readouterr().out
    assert not (tmp_path / "o.csv").exists()


def test_review_starts_on_the_first_candidate_with_macros(tmp_path, capsys):
    partial = {"fdcId": 1, "dataType": "Foundation", "description": "Lunchmeat, partial lab data",
               "foodNutrients": [{"nutrient": {"number": "255", "name": "Water"}, "amount": 70}]}
    client = FakeClient([partial, fixture("usda_foundation_oats.json")])

    usda_lookup.review_product(client, OATS, False, str(tmp_path / "o.csv"), dry_run=True)

    out = capsys.readouterr().out
    assert "1. Lunchmeat, partial lab data [Foundation, fdcId 1]  (no calorie/macro data)" in out
    assert "Candidate 2:" in out and "Candidate 1:" not in out
