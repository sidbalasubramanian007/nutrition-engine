import random
import db

# Maps each food (by name) to the meal slots it belongs in.
# Foods not listed here are flexible and can appear in any slot.
MEAL_SLOT_MAP = {
    # Breakfast only
    "Rolled Oats":               ["breakfast"],
    "Egg Whites":                ["breakfast"],
    # Breakfast + snack
    "Bananas":                   ["breakfast", "snack"],
    "0% Greek Yogurt":           ["breakfast", "snack"],
    "Nonfat Plain Greek Yogurt": ["breakfast", "snack"],
    "Whey Protein Powder":       ["breakfast", "snack"],
    # Lunch/Dinner carbs
    "Jasmine Rice":              ["lunch", "dinner"],
    "Sweet Potato":              ["lunch", "dinner"],
    "Quinoa":                    ["lunch", "dinner"],
    "Brown Rice":                ["lunch", "dinner"],
    # Lunch/Dinner proteins — ALL proteins must be listed here explicitly
    # so nothing leaks into breakfast by falling through the default
    "Chicken Breast":            ["lunch", "dinner"],
    "Organic Boneless Skinless Chicken Breast": ["lunch", "dinner"],
    "Wild Sockeye Salmon":       ["dinner"],
    "Lean Ground Turkey":        ["lunch", "dinner"],
    "Lean Ground Turkey (93/7)": ["lunch", "dinner"],
    "Organic Firm Tofu":         ["lunch", "dinner"],
    "Sirloin Steak":             ["dinner"],
    "Cod Fillet":                ["lunch", "dinner"],
    "Shrimp":                    ["lunch", "dinner"],
    # Fats / sides
    "Avocado":                   ["lunch", "dinner"],
    "Almonds":                   ["snack"],
}

def fetch_products_rows():
    """Runs the products query against Postgres and returns the raw rows."""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, calories, protein, carbs, fat, fiber, category, max_servings, location FROM products;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def rows_to_foods(rows):
    """Transforms raw product rows into the food dicts used by the solver."""
    foods = []
    for row in rows:
        # Safely check if the 9th column exists (for backwards compatibility in tests)
        location_val = row[8] if len(row) > 8 else "Grocery"
        
        foods.append({
            "name":         row[0],
            "calories":     float(row[1]),
            "protein":      float(row[2]),
            "carbs":        float(row[3]),
            "fat":          float(row[4]),
            "fiber":        float(row[5]),
            "category":     row[6],
            "max_servings": int(row[7]),
            "location":     location_val
        })
    return foods

def load_food_data(mode="grocery", restaurant=None):
    """Connects to Postgres and loads categorized items based on the active mode."""
    print("Step 1: Connecting to PostgreSQL database...")
    try:
        rows = fetch_products_rows()
        foods = rows_to_foods(rows)
        
        if mode == "grocery":
            # Strict grocery items only
            foods = [f for f in foods if f.get('location', 'Grocery') == 'Grocery']
            
        elif mode == "eating_out" and restaurant:
            # Groceries + items for the explicitly selected restaurant
            foods = [f for f in foods if f.get('location', 'Grocery') == 'Grocery' or f.get('location') == restaurant]
            
        print(f"-> Successfully loaded {len(foods)} items.")
        return foods
    except Exception as e:
        print(f"Database error: {e}")
        return None

def foods_for_slot(pool, slot):
    """
    Filter a food pool to items that belong in the given meal slot.
    Proteins not explicitly listed in MEAL_SLOT_MAP default to lunch/dinner only.
    """
    result = []
    for f in pool:
        if f['name'] in MEAL_SLOT_MAP:
            if slot in MEAL_SLOT_MAP[f['name']]:
                result.append(f)
        else:
            # Safe default: unmapped proteins → lunch/dinner only
            if f['category'] == 'lean_protein':
                if slot in ['lunch', 'dinner']:
                    result.append(f)
            else:
                result.append(f)
    return result

def pick_unique(pool, used_names):
    """Pick a random food from pool that hasn't been used today yet."""
    available = [f for f in pool if f['name'] not in used_names]
    return random.choice(available) if available else None

def build_meal_plan(foods, target_calories, target_protein, target_carbs, target_fat, restaurant=None, restaurant_meal=None):
    proteins = [f for f in foods if f['category'] == 'lean_protein']
    staples  = [f for f in foods if f['category'] == 'staple']

    bfast_carbs  = foods_for_slot(staples,  'breakfast')
    bfast_prots  = foods_for_slot(proteins, 'breakfast')
    lunch_prots  = foods_for_slot(proteins, 'lunch')
    dinner_prots = foods_for_slot(proteins, 'dinner')
    meal_carbs   = foods_for_slot(staples,  'lunch')
    snack_pool   = foods_for_slot(foods,    'snack')

    if not bfast_carbs or not lunch_prots or not dinner_prots or not meal_carbs:
        return None

    # Determine which location to pull from for Lunch and Dinner
    lunch_loc  = restaurant if restaurant_meal == "Lunch" else "Grocery"
    dinner_loc = restaurant if restaurant_meal == "Dinner" else "Grocery"

    # Helper to filter the current pool by the targeted location
    def filter_loc(pool, loc):
        return [f for f in pool if f.get('location', 'Grocery') == loc]

    used = []

    b_carb = pick_unique(filter_loc(bfast_carbs, 'Grocery'), used)
    if b_carb: used.append(b_carb['name'])

    b_prot = pick_unique(filter_loc(bfast_prots, 'Grocery'), used)
    if b_prot: used.append(b_prot['name'])

    l_prot = pick_unique(filter_loc(lunch_prots, lunch_loc), used)
    if l_prot: used.append(l_prot['name'])

    l_carb = pick_unique(filter_loc(meal_carbs, lunch_loc), used)
    if l_carb: used.append(l_carb['name'])

    d_prot = pick_unique(filter_loc(dinner_prots, dinner_loc), used)
    if d_prot: used.append(d_prot['name'])

    d_carb = pick_unique(filter_loc(meal_carbs, dinner_loc), used)
    if d_carb: used.append(d_carb['name'])

    snack1 = pick_unique(filter_loc(snack_pool, 'Grocery'), used)
    if snack1: used.append(snack1['name'])
    snack2 = pick_unique(filter_loc(snack_pool, 'Grocery'), used)

    meal_assignments = [
        ("Breakfast", [f for f in [b_carb, b_prot]    if f]),
        ("Lunch",     [f for f in [l_prot, l_carb]    if f]),
        ("Dinner",    [f for f in [d_prot, d_carb]    if f]),
        ("Snack",     [f for f in [snack1, snack2]    if f]),
    ]
    meal_assignments = [(m, items) for m, items in meal_assignments if items]

    result_items = []
    totals = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}

    for meal_name, meal_foods in meal_assignments:
        for food in meal_foods:
            max_s    = 1 if meal_name == "Snack" else min(food['max_servings'], 3)
            servings = random.randint(1, max_s)
            totals["calories"] += food["calories"] * servings
            totals["protein"]  += food["protein"]  * servings
            totals["carbs"]    += food["carbs"]    * servings
            totals["fat"]      += food["fat"]      * servings
            totals["fiber"]    += food["fiber"]    * servings
            result_items.append({
                "name":     food["name"],
                "servings": servings,
                "category": food["category"],
                "meal":     meal_name,
            })

    penalty = (
        abs(totals["calories"] - target_calories) * 20 +
        abs(totals["protein"]  - target_protein)  * 100 +
        abs(totals["carbs"]    - target_carbs)    * 20 +
        abs(totals["fat"]      - target_fat)      * 20 +
        max(0, totals["fiber"] - 35) * 50
    )

    totals["fiber"] = round(totals["fiber"], 1)
    return {"items": result_items, "macros": totals, "penalty": penalty}

def run_heuristic_solver(foods, target_calories=2800, target_protein=170,
                          target_carbs=390, target_fat=68, iterations=50000,
                          restaurant=None, restaurant_meal=None):
    """
    Runs the heuristic solver with structured meal planning and
    full four-macro penalty scoring.
    """
    print(f"\nStep 2: Starting Heuristic Engine ({iterations} structured combinations)...")
    best, lowest_penalty = None, float("inf")

    for _ in range(iterations):
        plan = build_meal_plan(foods, target_calories, target_protein, target_carbs, target_fat, restaurant, restaurant_meal)
        if plan and plan["penalty"] < lowest_penalty:
            lowest_penalty = plan["penalty"]
            best = plan

    return best

def display_meal_plan(winner):
    if not winner:
        print("No optimal plan found.")
        return

    print("\n==================================================")
    print("            OPTIMAL DAILY MEAL PLAN               ")
    print("==================================================")

    current_meal = None
    for item in winner['items']:
        if item['meal'] != current_meal:
            current_meal = item['meal']
            print(f"\n  [{current_meal.upper()}]")
        tag = f"[{item['category'].upper()}]"
        print(f"    - {item['servings']}x {item['name']} {tag}")

    print("\nFinal Macro Breakdown:")
    print(f" - Calories: {winner['macros']['calories']} kcal")
    print(f" - Protein:  {winner['macros']['protein']}g")
    print(f" - Carbs:    {winner['macros']['carbs']}g")
    print(f" - Fat:      {winner['macros']['fat']}g")
    print(f" - Fiber:    {winner['macros']['fiber']}g")
    print("==================================================")

if __name__ == "__main__":
    food_db = load_food_data()
    if food_db:
        winning_plan = run_heuristic_solver(food_db)
        display_meal_plan(winning_plan)