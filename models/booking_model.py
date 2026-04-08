from models.db import get_db
from utils.constants import ACTIVE_SLOT_STATUSES, STATUS_CHECKED_IN


BOOKING_COLUMNS = """
    booking_id, customer_id, name, phone, vehicle, brand_model,
    service, date, status, created_at, checked_in_at, completed_at, whatsapp_sent
"""


def row_to_booking(row):
    booking = dict(row)
    booking["customer_id"] = booking.get("customer_id") or ""
    booking["phone"] = booking.get("phone") or ""
    booking["brand_model"] = booking.get("brand_model") or ""
    booking["whatsapp_sent"] = int(booking.get("whatsapp_sent") or 0)
    booking["checked_in"] = booking.get("status") == STATUS_CHECKED_IN
    booking["is_manual"] = not bool(booking.get("customer_id"))
    return booking


def get_all_bookings():
    rows = get_db().execute(f"SELECT {BOOKING_COLUMNS} FROM bookings").fetchall()
    return [row_to_booking(row) for row in rows]


def search_bookings(query=None, date=None, status=None):
    normalized_query = (query or "").strip().lower()
    normalized_date = (date or "").strip() or None
    normalized_status = (status or "").strip().lower() or None
    search_term = f"%{normalized_query}%"

    rows = get_db().execute(
        f"""
        SELECT {BOOKING_COLUMNS}
        FROM bookings
        WHERE (
            ? = '' OR
            LOWER(booking_id) LIKE ? OR
            LOWER(phone) LIKE ? OR
            LOWER(vehicle) LIKE ?
        )
        AND (? IS NULL OR status = ?)
        AND (? IS NULL OR date = ?)
        ORDER BY COALESCE(created_at, checked_in_at, date, '') DESC
        """,
        (
            normalized_query,
            search_term,
            search_term,
            search_term,
            normalized_status,
            normalized_status,
            normalized_date,
            normalized_date,
        ),
    ).fetchall()
    return [row_to_booking(row) for row in rows]


def get_booking_by_id(booking_id):
    row = get_db().execute(
        f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE booking_id = ?",
        (booking_id,),
    ).fetchone()
    return row_to_booking(row) if row else None


def booking_id_exists(booking_id):
    row = get_db().execute(
        "SELECT 1 FROM bookings WHERE booking_id = ? LIMIT 1",
        (booking_id,),
    ).fetchone()
    return row is not None


def get_bookings_by_customer(customer_id):
    rows = get_db().execute(
        f"SELECT {BOOKING_COLUMNS} FROM bookings WHERE customer_id = ?",
        (customer_id,),
    ).fetchall()
    return [row_to_booking(row) for row in rows]


def create_booking(booking):
    get_db().execute(
        """
        INSERT INTO bookings (
            booking_id, customer_id, name, phone, vehicle, brand_model,
            service, date, status, created_at, checked_in_at, completed_at, whatsapp_sent
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            booking["booking_id"],
            booking.get("customer_id", ""),
            booking["name"],
            booking.get("phone", ""),
            booking["vehicle"],
            booking.get("brand_model", ""),
            booking["service"],
            booking["date"],
            booking["status"],
            booking.get("created_at", ""),
            booking.get("checked_in_at"),
            booking.get("completed_at"),
            int(booking.get("whatsapp_sent", 0) or 0),
        ),
    )


def update_booking_status(booking_id, status, checked_in_at=None, completed_at=None, whatsapp_sent=None):
    get_db().execute(
        """
        UPDATE bookings
        SET status = ?, checked_in_at = ?, completed_at = ?,
            whatsapp_sent = COALESCE(?, whatsapp_sent)
        WHERE booking_id = ?
        """,
        (status, checked_in_at, completed_at, whatsapp_sent, booking_id),
    )


def update_whatsapp_sent(booking_id, whatsapp_sent):
    get_db().execute(
        """
        UPDATE bookings
        SET whatsapp_sent = ?
        WHERE booking_id = ?
        """,
        (int(whatsapp_sent), booking_id),
    )


def get_latest_booking_id(prefix):
    row = get_db().execute(
        """
        SELECT booking_id
        FROM bookings
        WHERE booking_id LIKE ?
        ORDER BY CAST(SUBSTR(booking_id, ?) AS INTEGER) DESC
        LIMIT 1
        """,
        (f"{prefix}%", len(prefix) + 1),
    ).fetchone()
    return row["booking_id"] if row else None


def count_bookings_for_slot(date):
    placeholders = ", ".join("?" for _ in ACTIVE_SLOT_STATUSES)
    row = get_db().execute(
        f"""
        SELECT COUNT(*) AS total
        FROM bookings
        WHERE date = ? AND status IN ({placeholders})
        """,
        (date, *ACTIVE_SLOT_STATUSES),
    ).fetchone()
    return row["total"] if row else 0
