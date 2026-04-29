import psycopg2

def seed_elite():
    # Elite clean sources: High protein, low processing
    # (name, cal, prot, carb, fat, fiber, category, max_servings)
    elite_foods = [
        ("Sirloin Steak", 200, 30, 0, 8, 0.0, 'lean_protein', 3),
        ("Cod Fillet", 100, 20, 0, 1, 0.0, 'lean_protein', 4),
        ("Avocado", 240, 3, 12, 22, 10.0, 'staple', 2),
        ("Almonds", 160, 6, 6, 14, 3.0, 'staple', 2),
        ("Brown Rice", 215, 5, 45, 2, 3.5, 'staple', 6),
        ("Shrimp", 100, 20, 0, 1, 0.0, 'lean_protein', 4)
    ]

    conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
    cursor = conn.cursor()
    
    insert_query = """
    INSERT INTO products (name, calories, protein, carbs, fat, fiber, category, max_servings)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (name) DO NOTHING;
    """
    
    for f in elite_foods:
        cursor.execute(insert_query, f)
        
    conn.commit()
    cursor.close()
    conn.close()
    print("-> Elite clean sources injected.")

if __name__ == "__main__":
    seed_elite()