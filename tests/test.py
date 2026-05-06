import sqlite3
import pandas as pd

DB_PATH = r"db_files\dex_pipeline.db"

def get_db_connection():
    # Avoid automatic timestamp parsing to prevent errors
    return sqlite3.connect(DB_PATH, detect_types=0)

def print_top5_all_tables():
    conn = get_db_connection()
    try:
        # Get all table names
        tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table';", conn)
        table_names = tables['name'].tolist()
        print("Tables in DB:", table_names)

        # Fetch top 5 rows from each table
        for table in table_names:
            try:
                df = pd.read_sql(f"SELECT * FROM {table} LIMIT 5;", conn)
                print(f"\nTable: {table} | Rows fetched: {len(df)}")
                print(df)
            except Exception as e:
                print(f"\n⚠️ Error fetching table {table}: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    print_top5_all_tables()
