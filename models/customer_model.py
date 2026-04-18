import re
import sqlite3

from models.db import get_db
from utils.helpers import log_action, normalize_phone


# CHANGED: Admin split pages need reusable customer creation and lookup helpers.
def _generate_customer_id():
    rows = get_db().execute("SELECT id FROM customers WHERE id LIKE 'CUST%'").fetchall()
    highest = 1000
    for row in rows:
        match = re.search(r"(\d+)$", row["id"] or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"CUST{highest + 1}"


def get_customer_by_id(customer_id):
    row = get_db().execute(
        "SELECT id, name, phone, vehicle FROM customers WHERE id = ?",
        (customer_id,),
    ).fetchone()
    return dict(row) if row else None


def find_customer(name, phone, vehicle):
    row = get_db().execute(
        """
        SELECT id, name, phone, vehicle
        FROM customers
        WHERE LOWER(name) = LOWER(?)
          AND phone = ?
          AND LOWER(vehicle) = LOWER(?)
        """,
        (name, phone, vehicle),
    ).fetchone()
    return dict(row) if row else None


def get_customer_by_phone(phone):
    normalized_phone = normalize_phone(phone)
    row = get_db().execute(
        "SELECT id, name, phone, vehicle FROM customers WHERE phone = ?",
        (normalized_phone,),
    ).fetchone()
    return dict(row) if row else None


# CHANGED: Login now uses the requested phone-or-customer-id lookup in one query.
def get_customer_by_phone_or_id(identifier):
    normalized_identifier = (identifier or "").strip()
    normalized_phone = normalize_phone(normalized_identifier)
    normalized_customer_id = normalized_identifier.upper()

    try:
        row = get_db().execute(
            """
            SELECT id, name, phone, vehicle
            FROM customers
            WHERE phone = ? OR id = ?
            LIMIT 1
            """,
            (normalized_phone, normalized_customer_id),
        ).fetchone()
        return dict(row) if row else None
    except Exception as error:
        log_action("LOGIN DB ERROR", str(error))
        return None


# CHANGED: Registration now creates a real customer row with a unique phone number.
def create_customer(name, phone, vehicle):
    normalized_name = (name or "").strip()
    normalized_phone = normalize_phone(phone)
    normalized_vehicle = (vehicle or "").strip().upper()

    if not all([normalized_name, normalized_phone, normalized_vehicle]):
        return False, "All fields are required.", None
    if len(normalized_phone) != 10:
        return False, "Phone number must be exactly 10 digits.", None

    try:
        existing = get_customer_by_phone(normalized_phone)
    except Exception as error:
        log_action("REGISTRATION DUPLICATE CHECK ERROR", str(error))
        return False, "Registration failed. Please try again.", None

    if existing:
        return False, "Phone already registered", None

    customer = {
        "id": _generate_customer_id(),
        "name": normalized_name,
        "phone": normalized_phone,
        "vehicle": normalized_vehicle,
    }

    try:
        get_db().execute(
            """
            INSERT INTO customers (id, name, phone, vehicle)
            VALUES (?, ?, ?, ?)
            """,
            (customer["id"], customer["name"], customer["phone"], customer["vehicle"]),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        get_db().rollback()
        log_action("REGISTRATION DB ERROR", "duplicate phone")
        return False, "Phone already registered", None
    except Exception as error:
        get_db().rollback()
        log_action("REGISTRATION DB ERROR", str(error))
        return False, "Registration failed. Please try again.", None

    return True, "", customer


# CHANGED: Used by /admin/add-customer and walk-in registration.
def ensure_customer(phone, name, vehicle):
    normalized_phone = normalize_phone(phone)
    normalized_name = (name or "").strip()
    normalized_vehicle = (vehicle or "").strip().upper()

    existing = get_customer_by_phone(normalized_phone)
    if existing:
        return existing

    customer = {
        "id": _generate_customer_id(),
        "name": normalized_name,
        "phone": normalized_phone,
        "vehicle": normalized_vehicle,
    }
    get_db().execute(
        """
        INSERT INTO customers (id, name, phone, vehicle)
        VALUES (?, ?, ?, ?)
        """,
        (customer["id"], customer["name"], customer["phone"], customer["vehicle"]),
    )
    get_db().commit()
    return customer


# CHANGED: Supports /admin/search-customer for the walk-in customer lookup.
def search_customers(query, limit=5):
    normalized_query = (query or "").strip()
    if not normalized_query:
        return []

    search_term = f"%{normalized_query}%"
    rows = get_db().execute(
        """
        SELECT id, name, phone, vehicle
        FROM customers
        WHERE id LIKE ? OR phone LIKE ? OR vehicle LIKE ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (search_term, search_term, search_term, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def get_vehicles_by_customer(identifier):
    """NEW: Get customer vehicles by phone or customer_id"""
    customer = get_customer_by_phone_or_id(identifier)
    if not customer:
        return []
    
    db = get_db()
    rows = db.execute(
        "SELECT plate_number, brand, model FROM vehicles WHERE customer_id = ?", 
        (customer['id'],)
    ).fetchall()
    
    return [dict(row) for row in rows]


def get_customer_map():
    rows = get_db().execute("SELECT id, name, phone, vehicle FROM customers").fetchall()
    return {row["id"]: dict(row) for row in rows}
