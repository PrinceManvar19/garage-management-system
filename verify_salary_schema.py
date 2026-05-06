import sqlite3
import os

# DB path from app.py logic
LOCALAPPDATA = os.getenv("LOCALAPPDATA", r"C:\Users\ASUS\AppData\Local")
DB_PATH = os.path.join(LOCALAPPDATA, "GarageManagement", "garage.db")

print(f"Connecting to: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# List tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [row[0] for row in cursor.fetchall()]
print("Tables:", tables)

# Check workers
if 'workers' in tables:
    cursor.execute("PRAGMA table_info(workers);")
    print("\nworkers schema:")
    for col in cursor.fetchall():
        print(col)
else:
    print("workers table missing!")

# Check salary_records
if 'salary_records' in tables:
    cursor.execute("PRAGMA table_info(salary_records);")
    print("\nsalary_records schema:")
    for col in cursor.fetchall():
        print(col)
    
    # Check FK
    cursor.execute("PRAGMA foreign_key_list(salary_records);")
    fks = cursor.fetchall()
    print("\nFKs in salary_records:")
    for fk in fks:
        print(fk)
    
    # Check indexes for UNIQUE
    cursor.execute("PRAGMA index_list(salary_records);")
    indexes = cursor.fetchall()
    print("\nIndexes on salary_records:")
    for idx in indexes:
        print(idx)
else:
    print("salary_records table missing!")

conn.close()
