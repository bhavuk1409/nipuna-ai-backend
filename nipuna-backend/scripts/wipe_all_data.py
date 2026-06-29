"""
Wipe ALL data from the Nipuna AI Supabase database.
Uses psycopg2 (sync) to avoid asyncpg/pgbouncer prepared-statement conflicts.
Run from /nipuna-backend directory:
    python scripts/wipe_all_data.py
"""
import os
import psycopg2
from psycopg2 import sql

# Parse DATABASE_URL from .env and convert to psycopg2-compatible form
DATABASE_URL = ""
env_path = os.path.join(os.path.dirname(__file__), "../.env")
with open(env_path) as f:
    for line in f:
        if line.startswith("DATABASE_URL="):
            DATABASE_URL = line.split("=", 1)[1].strip()
            break

# Convert asyncpg URL -> psycopg2 URL
DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# Discover all tables in public schema
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;")
tables = [row[0] for row in cur.fetchall()]

print(f"🔴 Found {len(tables)} tables. Wiping all data...\n")

for table in tables:
    try:
        cur.execute(sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY CASCADE;").format(sql.Identifier(table)))
        print(f"  ✅ Truncated: {table}")
    except Exception as e:
        print(f"  ⚠️  Skipped {table}: {e}")
        conn.rollback()

cur.close()
conn.close()
print("\n✅ Done! All tables wiped.")
