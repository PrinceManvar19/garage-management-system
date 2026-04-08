import re
import sqlite3
from datetime import datetime, timedelta

from models.booking_model import (
    booking_id_exists,
    create_booking,
    get_booking_by_id as fetch_booking_by_id,
    get_bookings_by_customer,
    get_latest_booking_id,
    search_bookings,
    update_booking_status,
    update_whatsapp_sent,
)
from models.customer_model import get_customer_by_id, get_customer_map
from models.db import get_db
from services.slot_service import get_slot_availability
from utils.constants import (
    STATUS_APPROVED,
    STATUS_CHECKED_IN,
    STATUS_COMPLETED,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from utils.helpers import (
    format_date_display,
    format_datetime_display,
    get_status_display,
    parse_datetime,
    sort_bookings_newest_first,
)


PHONE_PATTERN = re.compile(r"^\d{10}$")


def enrich_booking(booking, customer_map=None):
    customer_map = customer_map or get_customer_map()
    enriched = dict(booking)
    customer = customer_map.get(enriched.get("customer_id", ""), {})
    if not enriched.get("phone"):
        enriched["phone"] = customer.get("phone", "")
    enriched["status_display"] = get_status_display(enriched.get("status"))
    enriched["formatted_date"] = format_date_display(enriched.get("date"))
    enriched["formatted_created_at"] = format_datetime_display(enriched.get("created_at"))
    enriched["formatted_checked_in_at"] = format_datetime_display(enriched.get("checked_in_at"))
    enriched["formatted_completed_at"] = format_datetime_display(enriched.get("completed_at"))
    return enriched


def _generate_incremental_id(prefix):
    latest_id = get_latest_booking_id(prefix)
    if not latest_id:
        return f"{prefix}1001"
    return f"{prefix}{int(latest_id.replace(prefix, '')) + 1:04d}"


def generate_booking_id():
    return _generate_incremental_id("BOOK")


def generate_manual_booking_id():
    return _generate_incremental_id("MANUAL")


def normalize_phone(phone):
    normalized = (phone or "").strip()
    normalized = normalized.replace("+91", "")
    normalized = re.sub(r"\D", "", normalized)
    if len(normalized) > 10 and normalized.startswith("91"):
        normalized = normalized[-10:]
    return normalized


def generate_unique_booking_id(prefix):
    latest_id = get_latest_booking_id(prefix)
    start_number = 1001 if not latest_id else int(latest_id.replace(prefix, "")) + 1
    for number in range(start_number, start_number + 25):
        booking_id = f"{prefix}{number:04d}"
        if not booking_id_exists(booking_id):
            return booking_id
    raise ValueError("Unable to generate a unique booking ID.")


def get_customer_bookings(customer_id):
    customer_map = get_customer_map()
    bookings = [enrich_booking(booking, customer_map) for booking in get_bookings_by_customer(customer_id)]
    return sort_bookings_newest_first(bookings)


def get_customer_dashboard_data(customer_id):
    bookings = get_customer_bookings(customer_id)
    completed_bookings = [booking for booking in bookings if booking.get("status") == STATUS_COMPLETED]
    latest_completed = sort_bookings_newest_first(completed_bookings)[0] if completed_bookings else None
    due_for_service = False
    last_service_date = None
    next_service_date = None

    if latest_completed is not None:
        completed_at = parse_datetime(latest_completed.get("completed_at")) or parse_datetime(latest_completed.get("date"))
        if completed_at and datetime.now() - completed_at > timedelta(days=90):
            due_for_service = True
        if completed_at:
            last_service_date = completed_at.strftime("%Y-%m-%d")
            next_service_date = (completed_at + timedelta(days=90)).strftime("%Y-%m-%d")

    return {
        "bookings": bookings,
        "latest_completed_booking": latest_completed,
        "due_for_service": due_for_service,
        "last_service_date": last_service_date,
        "next_service_date": next_service_date,
    }


def _validate_phone(phone):
    return bool(PHONE_PATTERN.fullmatch(normalize_phone(phone)))


def _begin_write_transaction():
    get_db().execute("BEGIN IMMEDIATE")


def _validate_booking_input(customer_id, phone, vehicle, service, date):
    if not vehicle:
        return False, "Vehicle number is required."
    if not service:
        return False, "Service is required."
    customer = get_customer_by_id((customer_id or "").strip().upper())
    if not customer:
        return False, "Customer account was not found."
    if not _validate_phone(phone or customer.get("phone", "")):
        return False, "Phone number must be exactly 10 digits."
    slot = get_slot_availability((date or "").strip())
    if not slot:
        return False, "No slots available for selected date."
    if slot["available"] <= 0:
        return False, "All slots are booked for this date."
    return True, ""


def create_booking_for_customer(customer_id, name, phone, vehicle, brand_model, service, date):
    is_valid, message = _validate_booking_input(customer_id, phone, vehicle.strip().upper(), service.strip(), date.strip())
    if not is_valid:
        return False, message, None
    customer = get_customer_by_id(customer_id.strip().upper())
    resolved_phone = normalize_phone(phone or customer.get("phone", ""))

    booking = {
        "booking_id": generate_unique_booking_id("BOOK"),
        "customer_id": customer_id,
        "name": name,
        "phone": resolved_phone,
        "vehicle": vehicle.strip().upper(),
        "brand_model": brand_model.strip(),
        "service": service.strip(),
        "date": date.strip(),
        "status": STATUS_PENDING,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "checked_in_at": None,
        "completed_at": None,
        "whatsapp_sent": 0,
    }
    try:
        _begin_write_transaction()
        slot = get_slot_availability(booking["date"])
        if not slot:
            get_db().rollback()
            return False, "No slots available for selected date.", None
        if slot["available"] <= 0:
            get_db().rollback()
            return False, "All slots are booked for this date.", None
        create_booking(booking)
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        return False, "Booking could not be saved right now. Please try again.", None
    return True, "", booking


def create_manual_booking(name, phone, vehicle, brand_model, service, date):
    if not all([name.strip(), vehicle.strip(), brand_model.strip(), service.strip()]):
        return False, "Please fill all manual entry fields.", None
    if not _validate_phone(phone):
        return False, "Phone number must be exactly 10 digits.", None

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    booking = {
        "booking_id": generate_unique_booking_id("MANUAL"),
        "customer_id": "",
        "name": name.strip(),
        "phone": normalize_phone(phone),
        "vehicle": vehicle.strip().upper(),
        "brand_model": brand_model.strip(),
        "service": service.strip(),
        "date": date,
        "status": STATUS_CHECKED_IN,
        "created_at": timestamp,
        "checked_in_at": timestamp,
        "completed_at": None,
        "whatsapp_sent": 0,
    }
    try:
        _begin_write_transaction()
        create_booking(booking)
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        return False, "Walk-in entry could not be saved right now. Please try again.", None
    return True, "", booking


def create_manual_booking_with_customer(customer_id, name, phone, vehicle, brand_model, service, date):
    normalized_customer_id = (customer_id or "").strip().upper()
    if normalized_customer_id:
        customer = get_customer_by_id(normalized_customer_id)
        if not customer:
            return False, "Customer ID was not found.", None
        name = customer.get("name", name)
        phone = customer.get("phone", phone)

    return create_manual_booking(name, phone, vehicle, brand_model, service, date)


def get_admin_bookings(filters=None):
    filters = filters or {}
    customer_map = get_customer_map()
    bookings = [
        enrich_booking(booking, customer_map)
        for booking in search_bookings(
            query=filters.get("query"),
            date=filters.get("date"),
            status=filters.get("status"),
        )
    ]
    return sort_bookings_newest_first(bookings)


def get_booking_by_id(booking_id):
    booking = fetch_booking_by_id(booking_id)
    customer_map = get_customer_map()
    return enrich_booking(booking, customer_map) if booking else None


def get_booking_stats(bookings):
    return {
        "total": len(bookings),
        "pending": len([b for b in bookings if b.get("status") == STATUS_PENDING]),
        "approved": len([b for b in bookings if b.get("status") == STATUS_APPROVED]),
        "completed": len([b for b in bookings if b.get("status") == STATUS_COMPLETED]),
        "rejected": len([b for b in bookings if b.get("status") == STATUS_REJECTED]),
    }


def approve_booking(booking_id):
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Booking not found.", None
    if booking.get("status") == STATUS_APPROVED:
        return False, "Booking already approved.", booking
    if booking.get("status") != STATUS_PENDING:
        return False, "Only pending bookings can be approved.", booking

    try:
        _begin_write_transaction()
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Booking not found.", None
        if booking.get("status") == STATUS_APPROVED:
            get_db().rollback()
            return False, "Booking already approved.", booking
        if booking.get("status") != STATUS_PENDING:
            get_db().rollback()
            return False, "Only pending bookings can be approved.", booking
        slot = get_slot_availability(booking["date"])
        if not slot or slot["available"] <= 0:
            get_db().rollback()
            return False, "No slots available for this date.", booking
        update_booking_status(booking_id, STATUS_APPROVED, None, None, 0)
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        return False, "Booking could not be approved right now. Please try again.", booking
    return True, "", fetch_booking_by_id(booking_id)


def reject_booking(booking_id):
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Booking not found.", None
    if booking.get("status") == STATUS_REJECTED:
        return False, "Booking already rejected.", booking
    if booking.get("status") != STATUS_PENDING:
        return False, "Only pending bookings can be rejected.", booking

    try:
        _begin_write_transaction()
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Booking not found.", None
        if booking.get("status") == STATUS_REJECTED:
            get_db().rollback()
            return False, "Booking already rejected.", booking
        if booking.get("status") != STATUS_PENDING:
            get_db().rollback()
            return False, "Only pending bookings can be rejected.", booking
        update_booking_status(booking_id, STATUS_REJECTED, None, None, 0)
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        return False, "Booking could not be rejected right now. Please try again.", booking
    return True, "", fetch_booking_by_id(booking_id)


def checkin_vehicle(booking_id, today):
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Invalid Booking ID.", None
    if booking.get("date") != today:
        return False, "This booking is not scheduled for today.", booking
    if booking.get("status") != STATUS_APPROVED:
        return False, "Booking must be approved before check-in.", booking

    checked_in_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        _begin_write_transaction()
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Invalid Booking ID.", None
        if booking.get("date") != today:
            get_db().rollback()
            return False, "This booking is not scheduled for today.", booking
        if booking.get("status") != STATUS_APPROVED:
            get_db().rollback()
            return False, "Booking must be approved before check-in.", booking
        update_booking_status(booking_id, STATUS_CHECKED_IN, checked_in_at, None)
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        return False, "Vehicle could not be checked-in right now. Please try again.", booking
    return True, "", fetch_booking_by_id(booking_id)


def complete_booking_by_id(booking_id):
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Booking not found.", None
    if booking.get("status") != STATUS_CHECKED_IN:
        return False, "Only checked-in vehicles can be marked complete.", booking

    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    try:
        _begin_write_transaction()
        booking = fetch_booking_by_id(booking_id)
        if not booking:
            get_db().rollback()
            return False, "Booking not found.", None
        if booking.get("status") != STATUS_CHECKED_IN:
            get_db().rollback()
            return False, "Only checked-in vehicles can be marked complete.", booking
        update_booking_status(booking_id, STATUS_COMPLETED, booking.get("checked_in_at"), completed_at, 0)
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        return False, "Vehicle could not be completed right now. Please try again.", booking
    return True, "", fetch_booking_by_id(booking_id)


def mark_whatsapp_sent(booking_id):
    booking = fetch_booking_by_id(booking_id)
    if not booking:
        return False, "Booking not found.", None
    try:
        _begin_write_transaction()
        update_whatsapp_sent(booking_id, 1)
        get_db().commit()
    except sqlite3.Error:
        get_db().rollback()
        return False, "WhatsApp tracking could not be updated right now.", booking
    return True, "", fetch_booking_by_id(booking_id)
