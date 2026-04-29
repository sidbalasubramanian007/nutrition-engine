def calculate_tdee(weight_lbs, height_ft, height_in, age, gender, activity_level, goal):
    # Convert units to metric (Standard for medical equations)
    weight_kg = weight_lbs * 0.453592
    height_cm = ((height_ft * 12) + height_in) * 2.54
    
    # BMR Calculation (Mifflin-St Jeor)
    if gender == "Male":
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) + 5
    else:
        bmr = (10 * weight_kg) + (6.25 * height_cm) - (5 * age) - 161
        
    # Activity Multipliers
    multipliers = {
        "Sedentary": 1.2,
        "Lightly Active": 1.375,
        "Moderately Active": 1.55,
        "Very Active": 1.725
    }
    
    tdee = bmr * multipliers.get(activity_level, 1.2)
    
    # Goal Adjustments
    if goal == "Bulking":
        tdee += 300
    elif goal == "Cutting":
        tdee -= 500
        
    return int(tdee)

# Add this to calculator.py
def estimate_protein(weight_lbs, goal):
    # Base recommendation: 1g per lb
    protein = weight_lbs
    
    if goal == "Bulking":
        protein = weight_lbs * 1.1 # Slightly higher for hypertrophy
    elif goal == "Cutting":
        protein = weight_lbs * 1.2 # Higher protein spares muscle in deficits
        
    return int(protein)