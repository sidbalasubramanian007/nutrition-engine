import psycopg2

def apply_tags():
    print("Step 1: Connecting to database to apply schema update...")
    try:
        conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
        cursor = conn.cursor()

        # 1. Alter the table to add a category column (defaulting everything to 'misc')
        cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'misc';")

        # 2. Tag the bakery/junk items based on keywords in their name
        bakery_keywords = ['Muffin', 'Bread', 'Cake', 'Blondie', 'Pretzel', 'Pancake', 'Waffle', 'Scone', 'Graham', 'Cookie', 'Tortilla', 'Brioche']
        for word in bakery_keywords:
            cursor.execute(f"UPDATE products SET category = 'bakery' WHERE name ILIKE '%{word}%';")

        # 3. Tag the lean proteins
        protein_keywords = ['Chicken', 'Salmon', 'Turkey', 'Yogurt', 'Tofu']
        for word in protein_keywords:
            cursor.execute(f"UPDATE products SET category = 'lean_protein' WHERE name ILIKE '%{word}%';")

        conn.commit()
        print("-> Successfully upgraded schema and tagged all items!")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    apply_tags()