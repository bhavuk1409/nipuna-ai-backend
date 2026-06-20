from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection


def ensure_alert_schema(connection: Connection) -> None:
    """Apply small compatibility DDL for notifications tables.

    This keeps older databases working when the app starts before Alembic
    migrations have been applied.
    """
    inspector = inspect(connection)
    if "alerts" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("alerts")}
    if "read_at" in columns:
        return

    if connection.dialect.name == "postgresql":
        ddl = "ALTER TABLE alerts ADD COLUMN read_at TIMESTAMPTZ"
    else:
        ddl = "ALTER TABLE alerts ADD COLUMN read_at TIMESTAMP"

    connection.execute(text(ddl))
