import sqlalchemy as sa
from sqlalchemy import text

def check_db(port, dbname):
    print(f"--- Checking port {port}, db {dbname} ---")
    url = f"postgresql://postgres:postgres@localhost:{port}/{dbname}"
    try:
        engine = sa.create_engine(url)
        with engine.connect() as conn:
            tables = conn.execute(text(
                "SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog', 'information_schema')"
            ))
            print("Tables:")
            for row in tables.fetchall():
                print(f"  {row[0]}.{row[1]}")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    check_db(55432, "postgres")
    check_db(55432, "nipuna_ai")
