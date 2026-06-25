import os
import sqlite3
from pathlib import Path

from flask import current_app, g


def _database_path():
    try:
        root_path = current_app.root_path
    except RuntimeError:
        root_path = os.path.dirname(os.path.abspath(__file__))

    data_dir = Path(root_path) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "garage.db"


def get_local_db():
    connection = sqlite3.connect(_database_path())
    connection.row_factory = sqlite3.Row
    return connection


def get_cached_local_db():
    if "local_db" not in g:
        g.local_db = get_local_db()
    return g.local_db


def close_local_db(_error=None):
    connection = g.pop("local_db", None)
    if connection is not None:
        connection.close()


def local_query(sql, params=None):
    connection = get_local_db()
    try:
        cursor = connection.execute(sql, params or ())
        return [dict(row) for row in cursor.fetchall()]
    finally:
        connection.close()


def local_query_one(sql, params=None):
    connection = get_local_db()
    try:
        cursor = connection.execute(sql, params or ())
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def init_local_db():
    connection = get_local_db()
    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS cache_bookings (
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
                completed_at TEXT,
                actual_visit_date TEXT,
                is_rescheduled INTEGER NOT NULL DEFAULT 0,
                whatsapp_sent INTEGER NOT NULL DEFAULT 0,
                msg_approved_sent INTEGER NOT NULL DEFAULT 0,
                msg_rejected_sent INTEGER NOT NULL DEFAULT 0,
                msg_checkedin_sent INTEGER NOT NULL DEFAULT 0,
                msg_completed_sent INTEGER NOT NULL DEFAULT 0,
                service_reminder_sent INTEGER NOT NULL DEFAULT 0,
                reminder_sent_at TEXT,
                reminder_snooze_until TEXT,
                source TEXT DEFAULT 'customer_portal'
            );

            CREATE TABLE IF NOT EXISTS cache_customers (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                phone TEXT,
                vehicle TEXT
            );

            CREATE TABLE IF NOT EXISTS cache_slots (
                date TEXT PRIMARY KEY,
                total INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_cache_bookings_date
                ON cache_bookings(date);
            CREATE INDEX IF NOT EXISTS idx_cache_bookings_status
                ON cache_bookings(status);
            CREATE INDEX IF NOT EXISTS idx_cache_bookings_customer
                ON cache_bookings(customer_id);
            """
        )
        connection.commit()
    finally:
        connection.close()


def init_app(app):
    app.teardown_appcontext(close_local_db)
    with app.app_context():
        init_local_db()
