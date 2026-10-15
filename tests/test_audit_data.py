import audit_data


def test_source_is_the_highest_priority_file_containing_the_name(small_sources):
    # food_data.csv beats data/seed_*.csv, which beats trader_joes_macros.json (setup_db's merge order)
    assert audit_data.source_by_name() == {
        "Oats": "food_data.csv",
        "Tofu": "data/seed_proteins.csv",
        "Lemon Muffins": "trader_joes_macros.json",
    }


def test_missing_trader_joes_file_is_skipped_quietly(small_sources, capsys):
    (small_sources / "trader_joes_macros.json").unlink()
    assert audit_data.source_by_name() == {"Oats": "food_data.csv", "Tofu": "data/seed_proteins.csv"}
    assert capsys.readouterr().out == ""


def test_usda_override_is_the_source_of_an_overridden_food(small_sources):
    (small_sources / "data" / "usda_overrides.csv").write_text(
        "Name,Calories,Protein,Carbs,Fat,Fiber,Fdc_Id,Serving_Grams\n"
        "Tofu,144,17.3,2.8,8.7,2.3,172475,100\n"
        "Not Loaded,100,1,1,1,0,1,100\n")
    sources = audit_data.source_by_name()
    assert sources["Tofu"] == "data/usda_overrides.csv"
    assert sources["Oats"] == "food_data.csv"
    assert "Not Loaded" not in sources
