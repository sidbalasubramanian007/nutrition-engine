import psycopg2

def seed_protein():
    # More diverse options for the engine to choose from
    proteins = [
        ("Chicken Breast", 110, 23, 0, 2, 0.0, 'lean_protein', 6),
        ("Wild Sockeye Salmon", 130, 21, 0, 4, 0.0, 'lean_protein', 4),
        ("Egg Whites", 50, 11, 0, 0, 0.0, 'lean_protein', 8),
        ("0% Greek Yogurt", 90, 16, 5, 0, 0.0, 'lean_protein', 5),
        ("Lean Ground Turkey", 160, 22, 0, 8, 0.0, 'lean_protein', 4),
        ("Whey Protein Powder", 120, 24, 3, 1, 0.0, 'lean_protein', 2),
        ("Organic Firm Tofu", 130, 14, 3, 7, 2.0, 'lean_protein', 4)
    ]

    conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
    cursor = conn.cursor()
    
    insert_query = """
    INSERT INTO products (name, calories, protein, carbs, fat, fiber, category, max_servings)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (name) DO UPDATE SET max_servings = EXCLUDED.max_servings;
    """
    
    for p in proteins:
        cursor.execute(insert_query, p)
        
    conn.commit()
    cursor.close()
    conn.close()
    print("-> Protein anchors seeded successfully.")

if __name__ == "__main__":
    seed_protein()