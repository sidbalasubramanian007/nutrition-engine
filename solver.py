import psycopg2
import random

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


def build_meal_plan(foods, target_calories, target_protein, target_carbs, target_fat):
    """
    Builds a structured daily meal plan with 4 meal slots.
    Assigns proteins to protein slots and staples to carb slots so
    every generated plan actually resembles a real day of eating.

    Meal template:
      Breakfast — carb-focused staple (oats, banana, rice, etc.)
      Lunch     — protein + carb
      Dinner    — protein + carb
      Snack     — protein (shake, yogurt, etc.)
    """
    proteins = [f for f in foods if f['category'] == 'lean_protein']
    staples  = [f for f in foods if f['category'] == 'staple']

    if len(proteins) < 2 or len(staples) < 2:
        return None

    # Pick unique foods for each slot so we don't repeat the same item twice
    chosen_proteins = random.sample(proteins, min(3, len(proteins)))
    chosen_staples  = random.sample(staples,  min(3, len(staples)))

    meal_assignments = [
        ("Breakfast", [chosen_staples[0]]),
        ("Lunch",     [chosen_proteins[0], chosen_staples[1]]),
        ("Dinner",    [chosen_proteins[1], chosen_staples[2] if len(chosen_staples) > 2 else chosen_staples[0]]),
        ("Snack",     [chosen_proteins[2] if len(chosen_proteins) > 2 else chosen_proteins[0]]),
    ]

    items  = []
    totals = {"calories": 0, "protein": 0.0, "carbs": 0.0, "fat": 0.0, "fiber": 0.0}

    for meal_name, meal_foods in meal_assignments:
        for food in meal_foods:
            servings = random.randint(1, min(food['max_servings'], 4))
            totals["calories"] += food["calories"] * servings
            totals["protein"]  += food["protein"]  * servings
            totals["carbs"]    += food["carbs"]    * servings
            totals["fat"]      += food["fat"]      * servings
            totals["fiber"]    += food["fiber"]    * servings
            items.append({
                "name":     food["name"],
                "servings": servings,
                "category": food["category"],
                "meal":     meal_name,
            })

    # Penalize deviation from ALL four macro targets, not just cal + protein
    penalty = (
        abs(totals["calories"] - target_calories) * 10 +
        abs(totals["protein"]  - target_protein)  * 15 +
        abs(totals["carbs"]    - target_carbs)     * 5  +
        abs(totals["fat"]      - target_fat)       * 8  +
        max(0, totals["fiber"] - 35) * 100
    )

    totals["fiber"] = round(totals["fiber"], 1)
    return {"items": items, "macros": totals, "penalty": penalty}


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
