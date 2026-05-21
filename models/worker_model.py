from models.db import get_db, query_dict, query_dict_one, execute_query
from utils.helpers import normalize_phone, log_action


def _ensure_worker_status_column():
    db = get_db()
    cursor = db.cursor()

    try:
        cursor.execute("""
            ALTER TABLE workers
            ADD COLUMN IF NOT EXISTS worker_status TEXT DEFAULT 'active'
        """)
        cursor.execute("""
            UPDATE workers
            SET worker_status = 'active'
            WHERE worker_status IS NULL OR TRIM(worker_status) = ''
        """)
        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        cursor.close()


def ensure_worker_status_column():
    _ensure_worker_status_column()


def generate_next_worker_id():
    rows = query_dict("SELECT id FROM workers WHERE id LIKE %s", ("WORK%",))
    used_numbers = set()
    for row in rows:
        suffix = str(row["id"] or "")[4:]
        if suffix.isdigit():
            used_numbers.add(int(suffix))
    next_number = 1001
    while next_number in used_numbers:
        next_number += 1
    return f"WORK{next_number}"


def get_all_workers():
    ensure_worker_status_column()
    rows = query_dict(
        "SELECT id, name, phone, monthly_salary, worker_status FROM workers ORDER BY id ASC"
    )
    return [dict(row) for row in rows]


def get_worker(worker_id):
    ensure_worker_status_column()
    row = query_dict_one(
        "SELECT id, name, phone, monthly_salary, worker_status FROM workers WHERE id = %s",
        (worker_id,),
    )
    return dict(row) if row else None


def create_worker(worker_id, name, phone, monthly_salary, worker_status="active"):
    ensure_worker_status_column()
    worker_id = (worker_id or "").strip().upper()
    name = (name or "").strip()
    norm_phone = normalize_phone(phone)
    worker_status = (worker_status or "active").strip().lower()
    try:
        monthly_salary = float(monthly_salary or 0)
    except (ValueError, TypeError):
        return False, "Monthly salary must be a number", None

    if not all([worker_id, name, norm_phone, monthly_salary is not None]):
        return False, "All fields are required", None
    if len(norm_phone) != 10:
        return False, "Phone must be exactly 10 digits", None
    if worker_status not in {"active", "inactive"}:
        worker_status = "active"

    existing = query_dict_one("SELECT id FROM workers WHERE phone = %s", (norm_phone,))
    if existing:
        return False, "Phone number already registered", None

    db = get_db()
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute(
            "INSERT INTO workers (id, name, phone, monthly_salary, worker_status) VALUES (%s, %s, %s, %s, %s)",
            (worker_id, name, norm_phone, monthly_salary, worker_status),
        )
        db.commit()
        return True, "", {"id": worker_id, "name": name, "phone": norm_phone,
                          "monthly_salary": monthly_salary, "worker_status": worker_status}
    except Exception as e:
        db.rollback()
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return False, "Worker ID already exists", None
        log_action("WORKER CREATE ERROR", str(e))
        return False, "Failed to create worker", None
    finally:
        if cursor is not None:
            cursor.close()


def update_worker(worker_id, name, phone, monthly_salary, worker_status="active"):
    ensure_worker_status_column()
    worker_id = (worker_id or "").strip().upper()
    name = (name or "").strip()
    norm_phone = normalize_phone(phone)
    worker_status = (worker_status or "active").strip().lower()
    try:
        monthly_salary = float(monthly_salary or 0)
    except (ValueError, TypeError):
        return False, "Monthly salary must be a number"

    if not worker_id or not name or not norm_phone:
        return False, "ID, name, phone required"
    if len(norm_phone) != 10:
        return False, "Phone must be 10 digits"
    if worker_status not in {"active", "inactive"}:
        return False, "Invalid worker status"

    existing = get_worker(worker_id)
    if not existing:
        return False, "Worker not found"

    phone_conflict = query_dict_one(
        "SELECT id FROM workers WHERE phone = %s AND id != %s",
        (norm_phone, worker_id),
    )
    if phone_conflict:
        return False, "Phone already used by another worker"

    db = get_db()
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute(
            """
            UPDATE workers
            SET name = %s, phone = %s, monthly_salary = %s, worker_status = %s
            WHERE id = %s
            """,
            (name, norm_phone, monthly_salary, worker_status, worker_id),
        )
        db.commit()
        return True, ""
    except Exception as e:
        db.rollback()
        log_action("WORKER UPDATE ERROR", str(e))
        return False, "Update failed"
    finally:
        if cursor is not None:
            cursor.close()


def delete_worker(worker_id):
    worker_id = (worker_id or "").strip().upper()
    if not worker_id:
        return False, "ID required"
    existing = get_worker(worker_id)
    if not existing:
        return False, "Worker not found"
    db = get_db()
    cursor = None
    try:
        cursor = db.cursor()
        cursor.execute("DELETE FROM workers WHERE id = %s", (worker_id,))
        db.commit()
        return True, ""
    except Exception as e:
        db.rollback()
        log_action("WORKER DELETE ERROR", str(e))
        return False, "Delete failed"
    finally:
        if cursor is not None:
            cursor.close()
