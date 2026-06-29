"""Import inventory from the NSE product CSV into the InventoryItem table.

Usage:
    .venv/bin/python import_inventory.py

The CSV path defaults to ~/Downloads/Invetory List.csv but can be overridden
with the first CLI argument:

    .venv/bin/python import_inventory.py /path/to/file.csv

What it does:
  1. Clears all existing InventoryItem rows.
  2. Reads every row from the CSV (columns: Code, Name, Group, Brand, Type,
     Size, Unit, Color, Amount, Created By, Created At).
  3. Inserts one InventoryItem per row — Name → name, Group → category,
     Unit → unit, Amount → rate (truncated to int), Code → hsn.
  4. Rows with a blank Name are skipped.
"""
import csv
import os
import sys

# Allow running from project root without activating venv manually — run.py
# already prepends the venv site-packages, so calling via .venv/bin/python
# works automatically.
CSV_DEFAULT = os.path.expanduser("~/Downloads/Invetory List.csv")
csv_path = sys.argv[1] if len(sys.argv) > 1 else CSV_DEFAULT

if not os.path.exists(csv_path):
    print(f"ERROR: CSV not found at {csv_path}")
    sys.exit(1)

from nse import create_app
from nse.extensions import db
from nse.models import InventoryItem

app = create_app()

with app.app_context():
    # 1. Clear existing inventory
    deleted = InventoryItem.query.delete()
    db.session.commit()
    print(f"Cleared {deleted} existing inventory item(s).")

    # 2. Read CSV (UTF-8 with BOM)
    count = 0
    skipped = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = (row.get("Name") or "").strip()
            if not name:
                skipped += 1
                continue

            try:
                rate_raw = (row.get("Amount") or "0").replace(",", "").strip()
                rate = int(float(rate_raw))
            except (ValueError, TypeError):
                rate = 0

            item = InventoryItem(
                name     = name,
                category = (row.get("Group") or "General").strip() or "General",
                unit     = (row.get("Unit")  or "Nos").strip()     or "Nos",
                rate     = rate,
                hsn      = (row.get("Code")  or "").strip(),
                active   = True,
            )
            db.session.add(item)
            count += 1

    db.session.commit()
    print(f"Imported {count} inventory item(s) ({skipped} blank-name rows skipped).")
    print("Done — inventory is ready.")
