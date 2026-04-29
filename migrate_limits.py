import psycopg2

def migrate():
    conn = psycopg2.connect(dbname="nutrition_db", host="localhost")
    cursor = conn.cursor()
    
    # 1. Add the column
    cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS max_servings INTEGER DEFAULT 3;")
    
    # 2. Set defaults for existing items (so we don't have NULLs)
    cursor.execute("UPDATE products SET max_servings = 3 WHERE max_servings IS NULL;")
    
    conn.commit()
    cursor.close()
    conn.close()
    print("-> Migration complete: max_servings column active.")

if __name__ == "__main__":
    migrate()