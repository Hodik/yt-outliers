import sqlite3

# Connect to your SQLite database
conn = sqlite3.connect("youtube.db")
cursor = conn.cursor()

# Disable foreign key constraints
cursor.execute("PRAGMA foreign_keys = OFF;")

# Retrieve all table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()

# Drop each table
for table_name in tables:
    cursor.execute(f"DROP TABLE IF EXISTS {table_name[0]};")

# Re-enable foreign key constraints
cursor.execute("PRAGMA foreign_keys = ON;")

# Commit changes and close the connection
conn.commit()
conn.close()
