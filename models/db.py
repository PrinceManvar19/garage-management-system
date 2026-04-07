import json
import os
import sqlite3
from pathlib import Path

from flask import current_app, g


def get_db():
    if "db" not in g:
        db_path = current_app.config["DATABASE"]
        directory = os.path.dirname(db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        g.db = connection
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT,
            vehicle TEXT
        );

        CREATE TABLE IF NOT EXISTS admins (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phone TEXT
        );

        CREATE TABLE IF NOT EXISTS bookings (
            booking_id TEXT PRIMARY KEY,
            customer_id TEXT,
            name TEXT NOT NULL,
            phone TEXT,
            vehicle TEXT NOT NULL,
            brand_model TEXT,
            service TEXT NOT NULL,
            date TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT,
            checked_in_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS slots (
            date TEXT PRIMARY KEY,
            total INTEGER NOT NULL DEFAULT 0
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_booking_id ON bookings(booking_id);
        CREATE INDEX IF NOT EXISTS idx_booking_date ON bookings(date);
        CREATE INDEX IF NOT EXISTS idx_customer_id ON bookings(customer_id);
        """
    )
    migrate_slots_table(db)
    seed_admins(db)
    db.commit()


def seed_admins(db):
    db.executemany(
        "INSERT OR IGNORE INTO admins (id, name, phone) VALUES (?, ?, ?)",
        [
            ("ADMIN001", "Owner 1", ""),
            ("ADMIN002", "Owner 2", ""),
        ],
    )


def _load_json_file(path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        try:
            return json.load(file)
        except json.JSONDecodeError:
            return default


def migrate_json_data():
    db = get_db()
    data_dir = Path(current_app.root_path) / "data"

    customers = _load_json_file(data_dir / "customers.json", [])
    for customer in customers:
        customer_id = (customer or {}).get("id", "").strip().upper()
        if not customer_id or customer_id.startswith("ADMIN"):
            continue
        db.execute(
            """
            INSERT OR IGNORE INTO customers (id, name, phone, vehicle)
            VALUES (?, ?, ?, ?)
            """,
            (
                customer_id,
                customer.get("name", "").strip(),
                customer.get("phone", "").strip(),
                customer.get("vehicle", "").strip().upper(),
            ),
        )

    bookings = _load_json_file(data_dir / "bookings.json", [])
    for booking in bookings:
        booking_id = (booking or {}).get("booking_id", "").strip().upper()
        if not booking_id:
            continue
        db.execute(
            """
            INSERT OR IGNORE INTO bookings (
                booking_id, customer_id, name, phone, vehicle, brand_model,
                service, date, status, created_at, checked_in_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking_id,
                booking.get("customer_id", "").strip().upper(),
                booking.get("name", "").strip(),
                booking.get("phone", "").strip(),
                booking.get("vehicle", "").strip().upper(),
                booking.get("brand_model", "").strip(),
                booking.get("service", "").strip(),
                booking.get("date", "").strip(),
                (booking.get("status", "pending") or "pending").strip().lower(),
                booking.get("created_at", "") or "",
                booking.get("checked_in_at"),
                booking.get("completed_at"),
            ),
        )

    slots = _load_json_file(data_dir / "slots.json", {})
    if isinstance(slots, dict):
        for date, slot in slots.items():
            slot = slot or {}
            db.execute(
                """
                INSERT OR IGNORE INTO slots (date, total)
                VALUES (?, ?)
                """,
                (str(date).strip(), int(slot.get("total", 0) or 0)),
            )

    db.commit()


def migrate_slots_table(db):
    slot_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(slots)").fetchall()
    }
    if "booked" not in slot_columns:
        return

    db.executescript(
        """
        ALTER TABLE slots RENAME TO slots_old;

        CREATE TABLE slots (
            date TEXT PRIMARY KEY,
            total INTEGER NOT NULL DEFAULT 0
        );

        INSERT INTO slots (date, total)
        SELECT date, total
        FROM slots_old;

        DROP TABLE slots_old;
        """
    )


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
        migrate_json_data()
