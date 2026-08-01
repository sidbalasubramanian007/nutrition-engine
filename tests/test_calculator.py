import calculator


# --- calculate_tdee ---

def test_calculate_tdee_male_sedentary_maintenance():
    # BMR (Mifflin-St Jeor, male) = 10*kg + 6.25*cm - 5*age + 5, kg/cm from 170lbs/6'1"
    assert calculator.calculate_tdee(170, 6, 1, 18, "Male", "Sedentary", "Maintenance") == 2213


def test_calculate_tdee_female_sedentary_maintenance():
    # Female BMR uses -161 instead of +5
    assert calculator.calculate_tdee(140, 5, 5, 25, "Female", "Sedentary", "Maintenance") == 1657


def test_calculate_tdee_bulking_adds_300():
    assert calculator.calculate_tdee(180, 5, 10, 22, "Male", "Very Active", "Bulking") == 3444


def test_calculate_tdee_cutting_subtracts_500():
    assert calculator.calculate_tdee(200, 6, 0, 30, "Male", "Moderately Active", "Cutting") == 2453


def test_calculate_tdee_unknown_activity_level_defaults_to_sedentary_multiplier():
    # activity_level not in the multipliers dict falls back to .get(..., 1.2), same as "Sedentary"
    with_bogus_level = calculator.calculate_tdee(170, 6, 1, 18, "Male", "Some Made Up Level", "Maintenance")
    with_sedentary = calculator.calculate_tdee(170, 6, 1, 18, "Male", "Sedentary", "Maintenance")
    assert with_bogus_level == with_sedentary == 2213


def test_calculate_tdee_zero_weight_edge_case():
    # weight=0 shouldn't crash; BMR math still runs on the height/age terms alone
    assert calculator.calculate_tdee(0, 6, 1, 18, "Male", "Sedentary", "Maintenance") == 1288


# --- estimate_protein ---

def test_estimate_protein_maintenance_is_one_gram_per_pound():
    assert calculator.estimate_protein(170, "Maintenance") == 170


def test_estimate_protein_bulking_multiplies_by_1_1():
    assert calculator.estimate_protein(170, "Bulking") == 187


def test_estimate_protein_cutting_multiplies_by_1_2():
    assert calculator.estimate_protein(170, "Cutting") == 204


def test_estimate_protein_zero_weight_edge_case():
    assert calculator.estimate_protein(0, "Maintenance") == 0


def test_estimate_protein_truncates_not_rounds():
    # 155 * 1.1 = 170.5 -> int() truncates to 170, not round()'s 171
    assert calculator.estimate_protein(155, "Bulking") == 170


def test_estimate_protein_unknown_goal_falls_back_to_maintenance_ratio():
    assert calculator.estimate_protein(170, "Recomp") == 170


# --- estimate_fat_and_carbs ---

def test_estimate_fat_and_carbs_known_values():
    fat_g, carbs_g = calculator.estimate_fat_and_carbs(2800, 170)
    assert (fat_g, carbs_g) == (70, 371)


def test_estimate_fat_and_carbs_second_known_value_pair():
    fat_g, carbs_g = calculator.estimate_fat_and_carbs(2000, 125)
    assert (fat_g, carbs_g) == (50, 262)


def test_estimate_fat_and_carbs_zero_calories_and_protein():
    assert calculator.estimate_fat_and_carbs(0, 0) == (0, 0)


def test_estimate_fat_and_carbs_protein_calories_exceed_total_floors_at_zero():
    # When protein_g*4 > total_calories, "remaining" is floored at 0 instead of going
    # negative, so fat/carbs come out (0, 0) rather than negative.
    fat_g, carbs_g = calculator.estimate_fat_and_carbs(100, 100)
    assert (fat_g, carbs_g) == (0, 0)
