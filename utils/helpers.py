from datetime import datetime, timedelta

from utils.constants import (
    STATUS_APPROVED,
    STATUS_CHECKED_IN,
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_REJECTED,
)


def get_status_display(status):
    status_map = {
        STATUS_PENDING: "Waiting for Approval",
        STATUS_APPROVED: "Approved",
        STATUS_CHECKED_IN: "Vehicle received at garage",
        STATUS_REJECTED: "Rejected",
        STATUS_COMPLETED: "Service completed",
    }
    normalized = (status or STATUS_PENDING).lower()
    return status_map.get(normalized, normalized.title())


def sort_bookings_newest_first(bookings):
    def booking_sort_key(booking):
        return booking.get("created_at") or booking.get("checked_in_at") or booking.get("date") or ""

    return sorted(bookings, key=booking_sort_key, reverse=True)


def get_today_date_string():
    return datetime.now().strftime("%Y-%m-%d")


def get_next_days(days=14):
    today = datetime.now().date()
    return [(today + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(days)]


def parse_datetime(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
