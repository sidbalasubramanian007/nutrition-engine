import psycopg2

def seed_carbs():
    # Adding high-quality, unprocessed staples
    carbs = [
        ("Jasmine Rice", 200, 4, 45, 0, 1.0, 'staple', 10),
        ("Rolled Oats", 150, 5, 27, 3, 4.0, 'staple', 10),
        ("Sweet Potato", 112, 2, 26, 0, 4.0, 'staple', 10),
        ("Quinoa", 120, 4, 21, 2, 3.0, 'staple', 10),
        ("Bananas", 105, 1, 27, 0, 3.0, 'staple', 5),
    ]

    conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
    cursor = conn.cursor()
    
    insert_query = """
    INSERT INTO products (name, calories, protein, carbs, fat, fiber, category, max_servings)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (name) DO NOTHING;
    """
    
    for c in carbs:
        cursor.execute(insert_query, c)
        
    conn.commit()
    cursor.close()
    conn.close()
    print("-> Clean carb staples seeded.")

if __name__ == "__main__":
    seed_carbs()