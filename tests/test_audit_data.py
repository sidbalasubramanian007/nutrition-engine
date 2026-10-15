import json

import pytest

import audit_data
import setup_db

HEADER = "Name,Calories,Protein,Carbs,Fat,Fiber,Category,Max_Servings,Location,Meal_Slots,Component_Type\n"


@pytest.fixture
def small_sources(tmp_path, monkeypatch):
    """Tiny data files with overlapping names, wired into setup_db's source paths."""
    (tmp_path / "data").mkdir()
    (tmp_path / "food_data.csv").write_text(HEADER + "Oats,150,5,27,3,4,staple,3,Grocery,breakfast,\n")
    (tmp_path / "data" / "seed_proteins.csv").write_text(
        HEADER + "Oats,140,5,25,3,4,staple,3,Grocery,breakfast,\nTofu,130,14,3,7,2,lean_protein,4,Grocery,lunch|dinner,\n")
    (tmp_path / "trader_joes_macros.json").write_text(json.dumps([
        {"name": "Tofu", "calories": 120, "protein": 12, "carbs": 3, "fat": 7, "fiber": 1},
        {"name": "Lemon Muffins", "calories": 450, "protein": 6, "carbs": 60, "fat": 21, "fiber": 1},
    ]))
    monkeypatch.setattr(setup_db, "FOOD_DATA_PATH", str(tmp_path / "food_data.csv"))
    monkeypatch.setattr(setup_db, "SEED_GLOB", str(tmp_path / "data" / "*.csv"))
    monkeypatch.setattr(setup_db, "TRADER_JOES_PATH", str(tmp_path / "trader_joes_macros.json"))
    monkeypatch.setattr(setup_db, "ROOT", str(tmp_path))
    return tmp_path


def test_source_is_the_highest_priority_file_containing_the_name(small_sources):
    # food_data.csv beats data/*.csv, which beats trader_joes_macros.json (setup_db's merge order)
    assert audit_data.source_by_name() == {
        "Oats": "food_data.csv",
        "Tofu": "data/seed_proteins.csv",
        "Lemon Muffins": "trader_joes_macros.json",
    }


def test_missing_trader_joes_file_is_skipped_quietly(small_sources, capsys):
    (small_sources / "trader_joes_macros.json").unlink()
    assert audit_data.source_by_name() == {"Oats": "food_data.csv", "Tofu": "data/seed_proteins.csv"}
    assert capsys.readouterr().out == ""
