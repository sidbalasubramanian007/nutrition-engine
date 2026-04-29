import psycopg2

def inspect_database():
    try:
        conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
        cursor = conn.cursor()
        
        # Query all items and sort them by protein (highest to lowest)
        cursor.execute("SELECT name, protein, calories FROM products ORDER BY protein DESC;")
        items = cursor.fetchall()
        
        print("\n--- DATABASE CONTENTS (Sorted by Protein) ---")
        for item in items:
            print(f"Protein: {item[1]}g | Calories: {item[2]} | {item[0]}")
            
        print(f"\nTotal items in database: {len(items)}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    inspect_database()