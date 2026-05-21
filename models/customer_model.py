import re

from models.db import get_db, query_dict, query_dict_one, execute_query
from utils.helpers import log_action, normalize_phone


def _generate_customer_id():
    rows = query_dict("SELECT id FROM customers WHERE id LIKE %s", ("CUST%",))
    highest = 1000
    for row in rows:
        match = re.search(r"(\d+)$", row["id"] or "")
        if match:
            highest = max(highest, int(match.group(1)))
    return f"CUST{highest + 1}"


def get_customer_by_id(customer_id):
    row = query_dict_one(
        "SELECT id, name, phone, vehicle FROM customers WHERE id = %s",
        (customer_id,),
    )
    return dict(row) if row else None


def find_customer(name, phone, vehicle):
    row = query_dict_one(
        """
        SELECT id, name, phone, vehicle
        FROM customers
        WHERE LOWER(name) = LOWER(%s)
          AND phone = %s
          AND LOWER(vehicle) = LOWER(%s)
        """,
        (name, phone, vehicle),
    )
    return dict(row) if row else None


def get_customer_by_phone(phone):
    normalized_phone = normalize_phone(phone)
    row = query_dict_one(
        "SELECT id, name, phone, vehicle FROM customers WHERE phone = %s",
        (normalized_phone,),
    )
    return dict(row) if row else None


def get_customer_by_phone_or_id(identifier):
    normalized_identifier = (identifier or "").strip()
    normalized_phone = normalize_phone(normalized_identifier)
    normalized_customer_id = normalized_identifier.upper()
    try:
        row = query_dict_one(
            """
            SELECT id, name, phone, vehicle
            FROM customers
            WHERE phone = %s OR id = %s
            LIMIT 1
            """,
            (normalized_phone, normalized_customer_id),
        )
        return dict(row) if row else None
    except Exception as error:
        log_action("LOGIN DB ERROR", str(error))
        return None


def _get_vehicles_for_customer_id(customer_id):
    rows = query_dict(
        """
        SELECT plate_number, brand, model
        FROM vehicles
        WHERE customer_id = %s
        ORDER BY plate_number ASC
        """,
        (customer_id,),
    )
    vehicles = [dict(row) for row in rows]
    if vehicles:
        return vehicles
    customer = get_customer_by_id(customer_id)
    legacy_vehicle = (customer or {}).get("vehicle", "").strip().upper()
    if not legacy_vehicle:
        return []
    return [{"plate_number": legacy_vehicle, "brand": "", "model": ""}]


def _set_primary_vehicle_if_missing(customer_id, plate_number):
    customer = get_customer_by_id(customer_id)
    if not customer:
        return
    current_vehicle = (customer.get("vehicle") or "").strip().upper()
    normalized_plate = (plate_number or "").strip().upper()
    if current_vehicle or not normalized_plate:
        return
    execute_query(
        "UPDATE customers SET vehicle = %s WHERE id = %s",
        (normalized_plate, customer_id),
    )


def _upsert_vehicle_record(db, customer_id, plate_number, brand="", model=""):
    normalized_plate = (plate_number or "").strip().upper()
    normalized_brand = (brand or "").strip()
    normalized_model = (model or "").strip()

    if not normalized_plate:
        raise ValueError("Vehicle number is required.")
    if not re.fullmatch(r"^[A-Z0-9\s-]{4,15}$", normalized_plate):
        raise ValueError("Invalid vehicle number format.")

    cursor = db.cursor()
    from psycopg2.extras import RealDictCursor
    cursor = db.cursor(cursor_factory=RealDictCursor)
    try:
        cursor.execute(
            """
            SELECT plate_number, customer_id, brand, model
            FROM vehicles WHERE plate_number = %s
            """,
            (normalized_plate,),
        )
        existing_vehicle = cursor.fetchone()

        if existing_vehicle:
            if existing_vehicle["customer_id"] != customer_id:
                raise ValueError("Vehicle number plate is already linked to another customer.")
            next_brand = normalized_brand or (existing_vehicle["brand"] or "")
            next_model = normalized_model or (existing_vehicle["model"] or "")
            cursor.execute(
                "UPDATE vehicles SET brand = %s, model = %s WHERE plate_number = %s",
                (next_brand, next_model, normalized_plate),
            )
            _set_primary_vehicle_if_missing(customer_id, normalized_plate)
            return {"plate_number": normalized_plate, "brand": next_brand, "model": next_model, "created": False}

        cursor.execute(
            "INSERT INTO vehicles (plate_number, customer_id, brand, model) VALUES (%s, %s, %s, %s)",
            (normalized_plate, customer_id, normalized_brand, normalized_model),
        )
        _set_primary_vehicle_if_missing(customer_id, normalized_plate)
        return {"plate_number": normalized_plate, "brand": normalized_brand, "model": normalized_model, "created": True}
    finally:
        cursor.close()


def create_customer(name, phone, vehicle, brand="", model=""):
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

    db = get_db()
    try:
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO customers (id, name, phone, vehicle) VALUES (%s, %s, %s, %s)",
            (customer["id"], customer["name"], customer["phone"], customer["vehicle"]),
        )
        cursor.close()
        _upsert_vehicle_record(db, customer["id"], normalized_vehicle, brand, model)
        db.commit()
    except Exception as error:
        db.rollback()
        log_action("REGISTRATION DB ERROR", str(error))
        if "unique" in str(error).lower() or "duplicate" in str(error).lower():
            return False, "Phone already registered", None
        return False, "Registration failed. Please try again.", None

    return True, "", customer


def ensure_customer(phone, name, vehicle, brand="", model=""):
    normalized_phone = normalize_phone(phone)
    normalized_name = (name or "").strip()
    normalized_vehicle = (vehicle or "").strip().upper()

    existing = get_customer_by_phone(normalized_phone)
    db = get_db()
    if existing:
        if normalized_vehicle:
            _upsert_vehicle_record(db, existing["id"], normalized_vehicle, brand, model)
            db.commit()
        return get_customer_by_id(existing["id"]) or existing

    customer = {
        "id": _generate_customer_id(),
        "name": normalized_name,
        "phone": normalized_phone,
        "vehicle": normalized_vehicle,
    }
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO customers (id, name, phone, vehicle) VALUES (%s, %s, %s, %s)",
        (customer["id"], customer["name"], customer["phone"], customer["vehicle"]),
    )
    cursor.close()
    if normalized_vehicle:
        _upsert_vehicle_record(db, customer["id"], normalized_vehicle, brand, model)
    db.commit()
    return customer


def search_customers(query, limit=5):
    normalized_query = (query or "").strip()
    if not normalized_query:
        return []
    search_term = f"%{normalized_query.upper()}%"
    normalized_phone = normalize_phone(normalized_query)
    phone_search_term = f"%{normalized_phone}%" if normalized_phone else None
    rows = query_dict(
        """
        SELECT DISTINCT c.id, c.name, c.phone, c.vehicle
        FROM customers c
        LEFT JOIN vehicles v ON v.customer_id = c.id
        WHERE UPPER(c.id) LIKE %s
           OR UPPER(c.name) LIKE %s
           OR UPPER(c.vehicle) LIKE %s
           OR UPPER(COALESCE(v.plate_number, '')) LIKE %s
           OR (%s IS NOT NULL AND c.phone LIKE %s)
        ORDER BY c.id ASC
        LIMIT %s
        """,
        (search_term, search_term, search_term, search_term, phone_search_term, phone_search_term, limit),
    )
    return [dict(row) for row in rows]


def get_vehicles_by_customer(identifier):
    customer = get_customer_by_phone_or_id(identifier)
    if not customer:
        return []
    return _get_vehicles_for_customer_id(customer["id"])


def get_customer_with_vehicles(identifier):
    customer = get_customer_by_phone_or_id(identifier)
    if not customer:
        return None
    return {"customer": customer, "vehicles": _get_vehicles_for_customer_id(customer["id"])}


def add_vehicle_to_customer(customer_id, plate_number, brand="", model=""):
    normalized_customer_id = (customer_id or "").strip().upper()
    customer = get_customer_by_id(normalized_customer_id)
    if not customer:
        raise ValueError("Customer not found.")
    db = get_db()
    vehicle = _upsert_vehicle_record(db, normalized_customer_id, plate_number, brand, model)
    db.commit()
    return vehicle


def get_customer_map():
    rows = query_dict("SELECT id, name, phone, vehicle FROM customers")
    return {row["id"]: dict(row) for row in rows}
