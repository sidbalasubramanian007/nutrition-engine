import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv("DB_HOST", "localhost"),
    port=os.getenv("DB_PORT", 5432),
    database=os.getenv("DB_NAME", "nutrition_db"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD", "")
)
cur = conn.cursor()

# Drop the incorrect table so we can rebuild it cleanly
cur.execute('DROP TABLE IF EXISTS products CASCADE;')

# Rebuild WITH the missing calories column
cur.execute('''
    CREATE TABLE products (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        calories NUMERIC,
        protein NUMERIC,
        carbs NUMERIC,
        fat NUMERIC,
        fiber NUMERIC,
        category VARCHAR(100),
        max_servings NUMERIC
    )
''')

# Insert test data that matches the exact names and categories your solver expects
cur.execute('''
    INSERT INTO products (name, calories, protein, carbs, fat, fiber, category, max_servings) VALUES 
    ('Rolled Oats', 150, 5, 27, 2.5, 4, 'staple', 3),
    ('Egg Whites', 125, 26, 2, 0, 0, 'lean_protein', 2),
    ('Chicken Breast', 165, 31, 0, 3.6, 0, 'lean_protein', 3),
    ('Chipotle Double Chicken', 320, 64, 0, 10, 0, 'lean_protein', 1),
    ('Jasmine Rice', 205, 4, 45, 0, 1, 'staple', 4),
    ('Pasta', 200, 7, 42, 1, 2, 'staple', 3),
    ('Sirloin Steak', 250, 26, 0, 15, 0, 'lean_protein', 2),
    ('Sweet Potato', 100, 2, 23, 0, 3, 'staple', 3),
    ('Almonds', 160, 6, 6, 14, 3.5, 'fat', 2),
    ('Peanut Butter', 190, 7, 8, 16, 2, 'fat', 2),
    ('Bananas', 105, 1, 27, 0, 3, 'carb', 2),
    ('Shake Smart PB & A', 450, 30, 55, 15, 5, 'snack', 1),
    ('0% Greek Yogurt', 100, 18, 6, 0, 0, 'lean_protein', 2),
    ('Whey Protein Powder', 120, 24, 3, 1.5, 0, 'lean_protein', 2)
''')

conn.commit()
cur.close()
conn.close()

print("Successfully rebuilt the 'products' table with the calories column!")