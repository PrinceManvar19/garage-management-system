"""Attendance model for worker daily attendance records."""

import datetime
from models.db import get_db, query_dict, query_dict_one, execute_query
from utils.helpers import log_action


VALID_STATUSES = {"present", "absent", "half_day", "leave", "holiday"}

STATUS_WEIGHTS = {
    "present": 1.0,
    "half_day": 0.5,
    "absent": 0.0,
    "leave": 0.0,
    "holiday": 0.0,
}


def ensure_attendance_table():
    """Create attendance_records table if it doesn't exist (PostgreSQL)."""
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance_records (
                id SERIAL PRIMARY KEY,
                worker_id TEXT NOT NULL,
                attendance_date TEXT NOT NULL,
                attendance_status TEXT NOT NULL DEFAULT 'present',
                check_in TEXT DEFAULT '',
                check_out TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'present',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (worker_id) REFERENCES workers(id),
                UNIQUE(worker_id, attendance_date)
            )
        """)
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_att_unique ON attendance_records(worker_id, attendance_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_att_date ON attendance_records(attendance_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_att_worker ON attendance_records(worker_id)")
        db.commit()

        # Add any missing columns safely
        required = {
            "attendance_status": "TEXT NOT NULL DEFAULT 'present'",
            "check_in": "TEXT DEFAULT ''",
            "check_out": "TEXT DEFAULT ''",
            "status": "TEXT NOT NULL DEFAULT 'present'",
        }
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'attendance_records'
        """)
        existing_cols = {row[0] for row in cursor.fetchall()}
        for col, ddl in required.items():
            if col not in existing_cols:
                cursor.execute(f"ALTER TABLE attendance_records ADD COLUMN {col} {ddl}")
        db.commit()
    finally:
        cursor.close()


def _normalize_status(status, default="present"):
    status = (status or default).strip().lower()
    return status if status in VALID_STATUSES else default


def upsert_attendance(worker_id, attendance_date, status, notes=""):
    ensure_attendance_table()
    worker_id = worker_id.strip().upper()
    status = _normalize_status(status)
    notes = (notes or "").strip()

    from models.worker_model import get_worker
    worker = get_worker(worker_id)
    if not worker:
        return False, f"Worker {worker_id} not found"

    try:
        execute_query("""
            INSERT INTO attendance_records (worker_id, attendance_date, status, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (worker_id, attendance_date) DO UPDATE SET
                status = EXCLUDED.status,
                notes = EXCLUDED.notes,
                updated_at = CURRENT_TIMESTAMP
        """, (worker_id, attendance_date, status, notes))
        log_action("ATTENDANCE_SAVED", f"{worker_id} {attendance_date} {status}")
        return True, "Attendance saved"
    except Exception as e:
        log_action("ATTENDANCE_SAVE_ERROR", str(e))
        return False, f"Save failed: {e}"


def get_attendance_for_date(attendance_date):
    ensure_attendance_table()
    rows = query_dict("""
        SELECT ar.*, w.name, w.phone
        FROM attendance_records ar
        JOIN workers w ON ar.worker_id = w.id
        WHERE ar.attendance_date = %s
        ORDER BY w.name ASC
    """, (attendance_date,))
    return [dict(row) for row in rows]


def get_attendance_for_worker(worker_id, year=None, month=None):
    ensure_attendance_table()
    worker_id = worker_id.strip().upper()
    query = "SELECT * FROM attendance_records WHERE worker_id = %s"
    params = [worker_id]

    if year:
        query += " AND TO_CHAR(attendance_date::date, 'YYYY') = %s"
        params.append(str(year))
    if month:
        query += " AND TO_CHAR(attendance_date::date, 'MM') = %s"
        params.append(f"{int(month):02d}")

    query += " ORDER BY attendance_date ASC"
    rows = query_dict(query, params)
    return [dict(row) for row in rows]


def calculate_month_attendance(worker_id, year, month):
    ensure_attendance_table()
    worker_id = worker_id.strip().upper()
    month_str = f"{int(month):02d}"
    date_prefix = f"{year}-{month_str}"

    rows = query_dict("""
        SELECT status FROM attendance_records
        WHERE worker_id = %s AND attendance_date LIKE %s
        ORDER BY attendance_date ASC
    """, (worker_id, date_prefix + "%"))

    total_records = len(rows)
    if total_records == 0:
        return {"total_days": 0, "attended_days": 0.0, "present_days": 0,
                "half_days": 0, "absent_days": 0, "leave_days": 0,
                "holiday_days": 0, "attendance_pct": 0.0}

    present_days = sum(1 for r in rows if r["status"] == "present")
    half_days = sum(1 for r in rows if r["status"] == "half_day")
    absent_days = sum(1 for r in rows if r["status"] == "absent")
    leave_days = sum(1 for r in rows if r["status"] == "leave")
    holiday_days = sum(1 for r in rows if r["status"] == "holiday")
    attended_days = present_days + (half_days * 0.5)
    attendance_pct = round((attended_days / total_records) * 100, 1) if total_records else 0.0

    return {"total_days": total_records, "attended_days": attended_days,
            "present_days": present_days, "half_days": half_days,
            "absent_days": absent_days, "leave_days": leave_days,
            "holiday_days": holiday_days, "attendance_pct": attendance_pct}


def get_today_summary():
    ensure_attendance_table()
    today = datetime.date.today().isoformat()
    rows = query_dict("""
        SELECT status, COUNT(*) as cnt
        FROM attendance_records
        WHERE attendance_date = %s
        GROUP BY status
    """, (today,))

    summary = {"present": 0, "absent": 0, "half_day": 0, "leave": 0, "holiday": 0, "total_workers": 0}
    status_counts = {row["status"]: row["cnt"] for row in rows}
    summary.update(status_counts)

    total_row = query_dict_one("SELECT COUNT(*) as cnt FROM workers WHERE worker_status = 'active'")
    summary["total_workers"] = total_row["cnt"] if total_row else 0
    return summary


def bulk_save_attendance(records):
    ensure_attendance_table()
    ok, err = 0, 0
    for rec in records:
        ok_rec, _ = upsert_attendance(
            rec.get("worker_id"),
            rec.get("attendance_date"),
            rec.get("status", "present"),
            rec.get("notes", "")
        )
        if ok_rec:
            ok += 1
        else:
            err += 1
    return ok, err


def get_attendance_history(worker_id=None, year=None, month=None, date_from=None, date_to=None):
    ensure_attendance_table()
    query = """
        SELECT ar.*, w.name, w.phone
        FROM attendance_records ar
        JOIN workers w ON ar.worker_id = w.id
        WHERE 1=1
    """
    params = []
    if worker_id:
        query += " AND ar.worker_id = %s"
        params.append(worker_id.strip().upper())
    if year:
        query += " AND TO_CHAR(ar.attendance_date::date, 'YYYY') = %s"
        params.append(str(year))
    if month:
        query += " AND TO_CHAR(ar.attendance_date::date, 'MM') = %s"
        params.append(f"{int(month):02d}")
    if date_from:
        query += " AND ar.attendance_date >= %s"
        params.append(date_from)
    if date_to:
        query += " AND ar.attendance_date <= %s"
        params.append(date_to)

    query += " ORDER BY ar.attendance_date DESC"
    rows = query_dict(query, params)
    return [dict(row) for row in rows]
