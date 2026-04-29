import psycopg2
import random

def load_food_data():
    """Connects to Postgres and loads categorized items with serving limits."""
    print("Step 1: Connecting to PostgreSQL database...")
    try:
        conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
        cursor = conn.cursor()
        
        # Pull everything directly from your live database
        # Index 0:name, 1:cal, 2:prot, 3:carb, 4:fat, 5:fiber, 6:cat, 7:max_servings
        cursor.execute("SELECT name, calories, protein, carbs, fat, fiber, category, max_servings FROM products;")
        rows = cursor.fetchall()
        
        foods = []
        for row in rows:
            foods.append({
                "name": row[0],
                "calories": row[1],
                "protein": row[2],
                "carbs": row[3],
                "fat": row[4],
                "fiber": float(row[5]),
                "category": row[6],
                "max_servings": row[7]
            })
            
        cursor.close()
        conn.close()
        print(f"-> Successfully loaded {len(foods)} categorized items from the database.")
        return foods
    except Exception as e:
        print(f"Database error: {e}")
        return None

def run_heuristic_solver(foods, target_calories=2800, target_protein=170, iterations=20000):
    print(f"\nStep 2: Starting Heuristic Engine (Running {iterations} random combinations)...")
    
    best_combination = None
    lowest_penalty = float('inf') 

    for _ in range(iterations):
        current_combo = []
        total_cal = 0
        total_protein = 0
        total_carbs = 0
        total_fat = 0
        total_fiber = 0
        bakery_servings = 0

        # Randomly select 3 to 5 unique items for the day
        num_items_in_day = random.randint(3, 5)
        selected_foods = random.sample(foods, num_items_in_day)

        for food in selected_foods:
            # Dynamic serving limit based on database settings
            limit = food['max_servings']
            servings = random.randint(1, limit)
            
            total_cal += food['calories'] * servings
            total_protein += food['protein'] * servings
            total_carbs += food['carbs'] * servings
            total_fat += food['fat'] * servings
            total_fiber += food['fiber'] * servings
            
            # Penalize junk food spam
            if food['category'] == 'bakery':
                bakery_servings += servings

            current_combo.append({
                "name": food['name'],
                "servings": servings,
                "category": food['category']
            })

        # --- THE HARDENED PENALTY FUNCTION ---
        calorie_penalty = abs(total_cal - target_calories) * 10
        protein_penalty = abs(total_protein - target_protein) * 15
        fiber_penalty = (max(0, total_fiber - 35)) * 100
        
        # 1. Anti-Spam Penalty: Heavily punish picking > 2 servings of any one item
        anti_spam_penalty = 0
        for item in current_combo:
            if item['servings'] > 2:
                anti_spam_penalty += (item['servings'] - 2) * 300 

        # 2. Diversity Bonus: Subtract points for every unique item picked (incentivizes variety)
        # Note: We subtract, so we use a negative value
        diversity_bonus = len(set([i['name'] for i in current_combo])) * 150

        # Bakery check (keep existing)
        bakery_penalty = 0
        if bakery_servings > 1:
            bakery_penalty = (bakery_servings - 1) * 1000

        total_penalty = calorie_penalty + protein_penalty + fiber_penalty + bakery_penalty + anti_spam_penalty - diversity_bonus
        
        if total_penalty < lowest_penalty:
            lowest_penalty = total_penalty
            best_combination = {
                "items": current_combo,
                "macros": {
                    "calories": total_cal,
                    "protein": total_protein,
                    "carbs": total_carbs,
                    "fat": total_fat,
                    "fiber": round(total_fiber, 1)
                }
            }

    return best_combination

def display_meal_plan(winner):
    if not winner:
        print("No optimal plan found.")
        return

    print("\n==================================================")
    print("            OPTIMAL DAILY MEAL PLAN               ")
    print("==================================================")
    print("Selected Items:")
    for item in winner['items']:
        tag = f"[{item['category'].upper()}]"
        print(f" - {item['servings']}x serving(s) of {item['name']} {tag}")
        
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