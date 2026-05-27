import psycopg2
import random

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


def load_food_data():
    """Connects to Postgres and loads categorized items with serving limits."""
    print("Step 1: Connecting to PostgreSQL database...")
    try:
        conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
        cursor = conn.cursor()
        cursor.execute("SELECT name, calories, protein, carbs, fat, fiber, category, max_servings FROM products;")
        rows = cursor.fetchall()
        foods = []
        for row in rows:
            foods.append({
                "name":         row[0],
                "calories":     row[1],
                "protein":      row[2],
                "carbs":        row[3],
                "fat":          row[4],
                "fiber":        float(row[5]),
                "category":     row[6],
                "max_servings": row[7]
            })
        cursor.close()
        conn.close()
        print(f"-> Successfully loaded {len(foods)} categorized items from the database.")
        return foods
    except Exception as e:
        print(f"Database error: {e}")
        return None


def foods_for_slot(pool, slot):
    """
    Filter a food pool to items that belong in the given meal slot.
    Proteins not explicitly listed in MEAL_SLOT_MAP default to lunch/dinner only
    so unmapped meats never leak into breakfast.
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


def build_meal_plan(foods, target_calories, target_protein, target_carbs, target_fat):
    """
    Builds a structured daily meal plan:
      Breakfast — carb (oats etc.) + protein (eggs/yogurt/whey)
      Lunch     — protein (chicken/turkey/tofu) + carb (rice/potato/quinoa)
      Dinner    — protein (salmon/steak/shrimp) + carb (different from lunch)
      Snack     — protein or light item (almonds, banana, etc.)

    Each food item is capped at 3 servings to prevent absurd quantities.
    All foods are unique within a day (no repeats across meals).
    """
    proteins = [f for f in foods if f['category'] == 'lean_protein']
    staples  = [f for f in foods if f['category'] == 'staple']

    # Slot-filtered pools
    bfast_carbs  = foods_for_slot(staples,  'breakfast')
    bfast_prots  = foods_for_slot(proteins, 'breakfast')
    lunch_prots  = foods_for_slot(proteins, 'lunch')
    dinner_prots = foods_for_slot(proteins, 'dinner')
    meal_carbs   = foods_for_slot(staples,  'lunch')
    snack_pool   = foods_for_slot(foods,    'snack')

    # Can't build a valid day without these
    if not bfast_carbs or not lunch_prots or not dinner_prots or not meal_carbs:
        return None

    # Pick unique foods for each slot — no food repeats across meals
    used = []

    b_carb = pick_unique(bfast_carbs, used)
    if b_carb: used.append(b_carb['name'])

    b_prot = pick_unique(bfast_prots, used)
    if b_prot: used.append(b_prot['name'])

    l_prot = pick_unique(lunch_prots, used)
    if l_prot: used.append(l_prot['name'])

    l_carb = pick_unique(meal_carbs, used)
    if l_carb: used.append(l_carb['name'])

    d_prot = pick_unique(dinner_prots, used)
    if d_prot: used.append(d_prot['name'])

    d_carb = pick_unique(meal_carbs, used)
    if d_carb: used.append(d_carb['name'])

    # Snack: pick up to 2 items (e.g. Almonds + Banana, or Whey + Banana)
    snack1 = pick_unique(snack_pool, used)
    if snack1: used.append(snack1['name'])
    snack2 = pick_unique(snack_pool, used)

    meal_assignments = [
        ("Breakfast", [f for f in [b_carb, b_prot]    if f]),
        ("Lunch",     [f for f in [l_prot, l_carb]    if f]),
        ("Dinner",    [f for f in [d_prot, d_carb]    if f]),
        ("Snack",     [f for f in [snack1, snack2]    if f]),
    ]
    # Drop empty meal slots
    meal_assignments = [(m, items) for m, items in meal_assignments if items]

    result_items = []
    totals = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}

    for meal_name, meal_foods in meal_assignments:
        for food in meal_foods:
            # Snacks are single-portion — cap at 1 serving
            # Main meals cap at 3 servings
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

    # Penalize deviation from ALL four macro targets
    penalty = (
        abs(totals["calories"] - target_calories) * 10 +
        abs(totals["protein"]  - target_protein)  * 15 +
        abs(totals["carbs"]    - target_carbs)     * 5  +
        abs(totals["fat"]      - target_fat)       * 8  +
        max(0, totals["fiber"] - 35) * 100
    )

    totals["fiber"] = round(totals["fiber"], 1)
    return {"items": result_items, "macros": totals, "penalty": penalty}


def run_heuristic_solver(foods, target_calories=2800, target_protein=170,
                          target_carbs=390, target_fat=68, iterations=50000):
    """
    Runs the heuristic solver with structured meal planning and
    full four-macro penalty scoring.
    """
    print(f"\nStep 2: Starting Heuristic Engine ({iterations} structured combinations)...")
    best, lowest_penalty = None, float("inf")

    for _ in range(iterations):
        plan = build_meal_plan(foods, target_calories, target_protein, target_carbs, target_fat)
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
