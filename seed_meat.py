import psycopg2

def seed_database():
    lean_proteins = [
        ("Organic Boneless Skinless Chicken Breast", 110, 23, 0, 2, 0.0),
        ("Wild Sockeye Salmon", 130, 21, 0, 4, 0.0),
        ("Lean Ground Turkey (93/7)", 160, 22, 0, 8, 0.0),
        ("Nonfat Plain Greek Yogurt", 90, 16, 5, 0, 0.0),
        ("Organic Firm Tofu", 130, 14, 3, 7, 2.0)
    ]

    try:
        conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
        cursor = conn.cursor()

        insert_query = """
        INSERT INTO products (name, calories, protein, carbs, fat, fiber)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (name) DO NOTHING;
        """

        print("Injecting lean anchors into the database...")
        for item in lean_proteins:
            cursor.execute(insert_query, item)
            
        conn.commit()
        print(f"Successfully seeded {len(lean_proteins)} pure protein sources.")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    seed_database()