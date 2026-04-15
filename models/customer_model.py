import re

from models.db import get_db


# CHANGED: Admin split pages need reusable customer creation and lookup helpers.
def _normalize_phone(phone):
    normalized = (phone or "").strip().replace("+91", "")
    normalized = re.sub(r"\D", "", normalized)
    if len(normalized) > 10 and normalized.startswith("91"):
        normalized = normalized[-10:]
    return normalized


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
    normalized_phone = phone.strip()
    row = get_db().execute(
        "SELECT id, name, phone, vehicle FROM customers WHERE phone = ?",
        (normalized_phone,),
    ).fetchone()
    return dict(row) if row else None


# CHANGED: Used by /admin/add-customer and walk-in registration.
def ensure_customer(phone, name, vehicle):
    normalized_phone = _normalize_phone(phone)
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


def get_customer_map():
    rows = get_db().execute("SELECT id, name, phone, vehicle FROM customers").fetchall()
    return {row["id"]: dict(row) for row in rows}
