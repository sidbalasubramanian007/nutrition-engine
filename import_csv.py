import csv
import db

conn = db.get_connection()
cur = conn.cursor()

# Add location column and clear old test data so we have a clean slate
cur.execute('ALTER TABLE products ADD COLUMN IF NOT EXISTS location VARCHAR(100) DEFAULT \'Grocery\';')
cur.execute('TRUNCATE TABLE products RESTART IDENTITY CASCADE;')

with open('food_data.csv', mode='r') as file:
    reader = csv.DictReader(file)
    for row in reader:
        cur.execute('''
            INSERT INTO products (name, calories, protein, carbs, fat, fiber, category, max_servings, location)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (
            row['Name'], float(row['Calories']), float(row['Protein']), 
            float(row['Carbs']), float(row['Fat']), float(row['Fiber']), 
            row['Category'], int(row['Max_Servings']), row['Location']
        ))

conn.commit()
cur.close()
conn.close()
print("Successfully imported national chain data!")