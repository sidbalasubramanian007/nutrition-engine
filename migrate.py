import os
import json
import psycopg2
from dotenv import load_dotenv

# Load variables if you want to store DB credentials there later
load_dotenv()

def migrate_data():
    # 1. Connect to your local PostgreSQL database
    # By default, Postgres uses your Mac's username as the default user
    try:
        conn = psycopg2.connect(
            dbname="nutrition_db",
            host="localhost"
        )
        cursor = conn.cursor()
        print("Connected to PostgreSQL successfully.")
    except Exception as e:
        print(f"Database connection failed: {e}")
        return

    # 2. Create the products table schema
    # We use FLOAT for fiber to handle decimal values precisely
    create_table_query = """
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name VARCHAR(255) UNIQUE NOT NULL,
        calories INTEGER NOT NULL,
        protein INTEGER NOT NULL,
        carbs INTEGER NOT NULL,
        fat INTEGER NOT NULL,
        fiber FLOAT NOT NULL
    );
    """
    cursor.execute(create_table_query)
    print("Table 'products' verified/created.")

    # 3. Read your local JSON file
    try:
        with open("trader_joes_macros.json", "r") as f:
            products_data = json.load(f)
    except FileNotFoundError:
        print("Error: trader_joes_macros.json not found. Run your scraper first.")
        return

    # 4. Insert data into the table
    # We use 'ON CONFLICT DO NOTHING' so running this twice won't duplicate items
    insert_query = """
    INSERT INTO products (name, calories, protein, carbs, fat, fiber)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (name) DO NOTHING;
    """

    inserted_count = 0
    for item in products_data:
        cursor.execute(insert_query, (
            item['name'],
            item['calories'],
            item['protein'],
            item['carbs'],
            item['fat'],
            item['fiber']
        ))
        inserted_count += cursor.rowcount

    # 5. Commit changes and close the connection
    conn.commit()
    cursor.close()
    conn.close()
    
    print(f"Migration complete! Successfully loaded {inserted_count} new items into the database.")

if __name__ == "__main__":
    migrate_data()