import random
import db

def fetch_products_rows():
    """Runs the products query against Postgres and returns the raw rows."""
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, calories, protein, carbs, fat, fiber, category, max_servings, location, meal_slots FROM products;")
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def rows_to_foods(rows):
    """Transforms raw product rows into the food dicts used by the solver."""
    foods = []
    for row in rows:
        foods.append({
            "name":         row[0],
            "calories":     float(row[1]),
            "protein":      float(row[2]),
            "carbs":        float(row[3]),
            "fat":          float(row[4]),
            "fiber":        float(row[5]),
            "category":     row[6],
            "max_servings": int(row[7]),
            "location":     row[8],
            "meal_slots":   list(row[9]),
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
    """Filter a food pool to items whose meal_slots include the given slot."""
    return [f for f in pool if slot in f['meal_slots']]

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

def build_restaurant_order(foods, target_calories, target_protein, target_carbs, target_fat):
    """Builds a single custom order from a restaurant's ingredient pool."""
    # Pick 2 to 5 random components (e.g., meat, rice, beans, guac)
    num_items = random.randint(2, min(5, len(foods)))
    selected_foods = random.sample(foods, k=num_items)
    
    totals = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}
    result_items = []
    
    for food in selected_foods:
        # Allow up to 2 servings (e.g., double meat or double rice)
        servings = random.randint(1, 2) 
        totals["calories"] += food["calories"] * servings
        totals["protein"]  += food["protein"]  * servings
        totals["carbs"]    += food["carbs"]    * servings
        totals["fat"]      += food["fat"]      * servings
        totals["fiber"]    += food["fiber"]    * servings
        
        result_items.append({
            "name": food["name"],
            "servings": servings,
            "category": food["category"],
            "meal": "Order"
        })
        
    penalty = (
        abs(totals["calories"] - target_calories) * 20 +
        abs(totals["protein"]  - target_protein)  * 100 +
        abs(totals["carbs"]    - target_carbs)    * 20 +
        abs(totals["fat"]      - target_fat)      * 20
    )
    
    totals["fiber"] = round(totals["fiber"], 1)
    return {"items": result_items, "macros": totals, "penalty": penalty}

def run_restaurant_solver(foods, target_calories, target_protein, target_carbs, target_fat, iterations=50000):
    best, lowest_penalty = None, float("inf")
    
    for _ in range(iterations):
        plan = build_restaurant_order(foods, target_calories, target_protein, target_carbs, target_fat)
        if plan and plan["penalty"] < lowest_penalty:
            lowest_penalty = plan["penalty"]
            best = plan
            
    return best

if __name__ == "__main__":
    food_db = load_food_data()
    if food_db:
        winning_plan = run_heuristic_solver(food_db)
        display_meal_plan(winning_plan)
