"""Wave 11 idempotent migration — adds new columns to existing SQLite tables.

New TABLES (visit_defects, broadcasts, installments, milestone_logs) are created
automatically by db.create_all() on app startup. This script only handles the
new COLUMNS on pre-existing tables, which db.create_all() cannot add. Idempotent
via PRAGMA table_info — safe to run repeatedly.

Run:  .venv/bin/python migrate_wave11.py
"""
from nse import create_app
from nse.extensions import db
from sqlalchemy import text

# (table, column, DDL type)
COLUMNS = [
    ("contracts",           "renewed_from_id",   "INTEGER"),
    ("visits",              "checkin_at",        "DATETIME"),
    ("visits",              "checkout_at",       "DATETIME"),
    ("visits",              "checkin_note",      "VARCHAR(255)"),
    ("amc_plans",           "sla_hours",         "INTEGER"),
    ("service_requests",    "sla_due_at",        "DATETIME"),
    ("service_requests",    "first_response_at", "DATETIME"),
    ("service_quotations",  "gateway_order_id",  "VARCHAR(120)"),
    ("service_quotations",  "gateway_payment_id","VARCHAR(120)"),
]

app = create_app()
with app.app_context():
    db.create_all()  # creates the new tables
    conn = db.session
    for table, col, ddl in COLUMNS:
        cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
        if col in cols:
            print(f"  = {table}.{col} already present")
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        print(f"  + added {table}.{col}")
    # Backfill sla_hours from response_time where sensible (default 48)
    conn.execute(text("UPDATE amc_plans SET sla_hours = 48 WHERE sla_hours IS NULL"))
    conn.commit()
    print("Wave 11 migration complete.")
