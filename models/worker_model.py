import sqlite3

from models.db import get_db
from utils.helpers import normalize_phone, log_action


def ensure_worker_status_column():
    """Add worker_status for existing SQLite databases."""
    columns = {
        row["name"]
        for row in get_db().execute("PRAGMA table_info(workers)").fetchall()
    }
    if "worker_status" not in columns:
        get_db().execute(
            "ALTER TABLE workers ADD COLUMN worker_status TEXT NOT NULL DEFAULT 'active'"
        )
        get_db().commit()


def generate_next_worker_id():
    """Generate the next editable worker ID such as WORK1001."""
    ensure_worker_status_column()
    rows = get_db().execute("SELECT id FROM workers WHERE id LIKE 'WORK%'").fetchall()
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
    """Get all workers ordered by ID."""
    ensure_worker_status_column()
    rows = get_db().execute(
        "SELECT id, name, phone, monthly_salary, worker_status FROM workers ORDER BY id ASC"
    ).fetchall()
    return [dict(row) for row in rows]


def get_worker(worker_id):
    """Get single worker by ID."""
    ensure_worker_status_column()
    row = get_db().execute(
        "SELECT id, name, phone, monthly_salary, worker_status FROM workers WHERE id = ?",
        (worker_id,),
    ).fetchone()
    return dict(row) if row else None


def create_worker(worker_id, name, phone, monthly_salary, worker_status="active"):
    """Create new worker. Returns (success, message, worker_data)."""
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

    try:
        # Check phone unique
        existing = get_db().execute(
            "SELECT id FROM workers WHERE phone = ?",
            (norm_phone,),
        ).fetchone()
        if existing:
            return False, "Phone number already registered", None

        get_db().execute(
            """
            INSERT INTO workers (id, name, phone, monthly_salary, worker_status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (worker_id, name, norm_phone, monthly_salary, worker_status),
        )
        get_db().commit()
        return True, "", {
            "id": worker_id,
            "name": name,
            "phone": norm_phone,
            "monthly_salary": monthly_salary,
            "worker_status": worker_status,
        }
    except sqlite3.IntegrityError:
        get_db().rollback()
        return False, "Worker ID already exists", None
    except Exception as e:
        get_db().rollback()
        log_action("WORKER CREATE ERROR", str(e))
        return False, "Failed to create worker", None


def update_worker(worker_id, name, phone, monthly_salary, worker_status="active"):
    """Update existing worker. Returns (success, message)."""
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

    # Check if worker exists
    existing = get_worker(worker_id)
    if not existing:
        return False, "Worker not found"

    # Check phone unique (allow same if unchanged)
    phone_conflict = get_db().execute(
        "SELECT id FROM workers WHERE phone = ? AND id != ?",
        (norm_phone, worker_id),
    ).fetchone()
    if phone_conflict:
        return False, "Phone already used by another worker"

    try:
        get_db().execute(
            """
            UPDATE workers
            SET name = ?, phone = ?, monthly_salary = ?, worker_status = ?
            WHERE id = ?
            """,
            (name, norm_phone, monthly_salary, worker_status, worker_id),
        )
        if get_db().total_changes == 0:
            return False, "No changes made or worker not found"
        get_db().commit()
        return True, ""
    except Exception as e:
        get_db().rollback()
        log_action("WORKER UPDATE ERROR", str(e))
        return False, "Update failed"


def delete_worker(worker_id):
    """Delete worker. Returns (success, message)."""
    ensure_worker_status_column()
    worker_id = (worker_id or "").strip().upper()
    if not worker_id:
        return False, "ID required"

    existing = get_worker(worker_id)
    if not existing:
        return False, "Worker not found"

    try:
        get_db().execute("DELETE FROM workers WHERE id = ?", (worker_id,))
        get_db().commit()
        return True, ""
    except Exception as e:
        get_db().rollback()
        log_action("WORKER DELETE ERROR", str(e))
        return False, "Delete failed"
