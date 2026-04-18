import csv
import zipfile
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from urllib.parse import quote

from flask import Blueprint, jsonify, Response, flash, redirect, render_template, request, session, url_for

from models.db import get_db
from models.booking_model import update_message_flags
from services.booking_service import (
    approve_booking as approve_booking_service,
    build_whatsapp_message,
    checkin_vehicle,
    complete_booking_by_id,
    create_manual_booking_with_customer,
    enrich_booking,
    get_admin_bookings,
    get_booking_by_id,
    get_booking_stats,
    normalize_phone,
    reject_booking as reject_booking_service,
)
from services.slot_service import get_slots_for_admin, set_slot_total
from utils.constants import STATUS_APPROVED, STATUS_IN_GARAGE, STATUS_COMPLETED, STATUS_PENDING, STATUS_REJECTED
from models.customer_model import (
    ensure_customer,
    get_customer_by_phone,
    get_customer_by_id,
    get_customer_map,
    search_customers,
)
from utils.helpers import format_date_display, format_datetime_display, get_today_date_string, log_action


admin_bp = Blueprint("admin", __name__)


def _require_admin():
    return session.get("role") == "admin"


def _redirect_with_whatsapp(booking_id, booking, fallback_response):
    if not booking:
        return fallback_response

    whatsapp_message, flags = build_whatsapp_message(booking)
    phone = normalize_phone(booking.get("phone", ""))
    if not whatsapp_message or not phone:
        return fallback_response

    try:
        if flags:
            update_message_flags(booking_id, **flags)
            get_db().commit()
    except Exception as error:
        get_db().rollback()
        log_action("DB ERROR UPDATE MSG FLAGS", f"{booking_id} - {error}")
        flash("Booking updated, but notification flags could not be saved.", "warning")
        return fallback_response

    encoded = quote(whatsapp_message)
    whatsapp_url = f"https://wa.me/91{phone}?text={encoded}"
    return redirect(whatsapp_url)


def _csv_response(filename, headers, rows):
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"' },
    )


def _normalize_csv_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y %H:%M")
    return str(value)


def _format_csv_date(value):
    return _normalize_csv_value(format_date_display(value))


def _format_csv_datetime(value):
    return _normalize_csv_value(format_datetime_display(value))


BOOKING_EXPORT_HEADERS = [
    "booking_id",
    "customer_id",
    "name",
    "phone",
    "vehicle",
    "brand_model",
    "service",
    "date",
    "status",
    "created_at",
    "checked_in_at",
    "completed_at",
]

CUSTOMER_EXPORT_HEADERS = ["id", "name", "phone", "vehicle"]
GARAGE_EXPORT_HEADERS = ["booking_id", "name", "phone", "vehicle", "brand_model", "service", "date", "checked_in_at"]
EXPORT_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_IN_GARAGE, STATUS_COMPLETED, STATUS_REJECTED}


def _build_last_7_days_data(bookings):
    today = datetime.strptime(get_today_date_string(), "%Y-%m-%d").date()
    days = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    counts = {day.strftime("%Y-%m-%d"): 0 for day in days}

    for booking in bookings:
        booking_date = booking.get("date")
        if booking_date in counts:
            counts[booking_date] += 1

    return [{"date": format_date_display(date), "count": count} for date, count in counts.items()]


def _booking_filter_clause(from_date="", to_date="", status="", garage_only=False):
    clauses = []
    params = []

    if garage_only:
        clauses.append("status = ?")
        params.append(STATUS_IN_GARAGE)
    elif status in EXPORT_STATUSES:
        clauses.append("status = ?")
        params.append(status)

    if from_date:
        clauses.append("date >= ?")
        params.append(from_date)
    if to_date:
        clauses.append("date <= ?")
        params.append(to_date)

    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where_sql, params


def _fetch_booking_export_rows(from_date="", to_date="", status="", garage_only=False):
    where_sql, params = _booking_filter_clause(from_date, to_date, status, garage_only)
    return get_db().execute(
        f"""
        SELECT booking_id, customer_id, name, phone, vehicle, brand_model, service,
               date, status, created_at, checked_in_at, completed_at
        FROM bookings
        {where_sql}
        ORDER BY date DESC, COALESCE(created_at, checked_in_at, '') DESC
        """,
        params,
    ).fetchall()


def _fetch_customer_export_rows():
    return get_db().execute(
        "SELECT id, name, phone, vehicle FROM customers ORDER BY id ASC"
    ).fetchall()


def _booking_csv_rows(rows):
    return [
        [
            _normalize_csv_value(row["booking_id"]),
            _normalize_csv_value(row["customer_id"]),
            _normalize_csv_value(row["name"]),
            _normalize_csv_value(row["phone"]),
            _normalize_csv_value(row["vehicle"]),
            _normalize_csv_value(row["brand_model"]),
            _normalize_csv_value(row["service"]),
            _format_csv_date(row["date"]),
            _normalize_csv_value(row["status"]),
            _format_csv_datetime(row["created_at"]),
            _format_csv_datetime(row["checked_in_at"]),
            _format_csv_datetime(row["completed_at"]),
        ]
        for row in rows
    ]


def _garage_csv_rows(rows):
    return [
        [
            _normalize_csv_value(row["booking_id"]),
            _normalize_csv_value(row["name"]),
            _normalize_csv_value(row["phone"]),
            _normalize_csv_value(row["vehicle"]),
            _normalize_csv_value(row["brand_model"]),
            _normalize_csv_value(row["service"]),
            _format_csv_date(row["date"]),
            _format_csv_datetime(row["checked_in_at"]),
        ]
        for row in rows
    ]


def _customer_csv_rows(rows):
    return [
        [
            _normalize_csv_value(row["id"]),
            _normalize_csv_value(row["name"]),
            _normalize_csv_value(row["phone"]),
            _normalize_csv_value(row["vehicle"]),
        ]
        for row in rows
    ]


def _csv_string(headers, rows):
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def _count_booking_exports(from_date="", to_date="", status="", garage_only=False):
    where_sql, params = _booking_filter_clause(from_date, to_date, status, garage_only)
    row = get_db().execute(f"SELECT COUNT(*) AS total FROM bookings {where_sql}", params).fetchone()
    return row["total"] if row else 0


def _render_admin_dashboard(filters=None, booking_data=None, checkin_booking_id=""):
    filters = filters or {
        "query": request.args.get("query", ""),
        "date": request.args.get("date", ""),
        "status": request.args.get("status", ""),
    }
    today = get_today_date_string()
    all_bookings = get_admin_bookings()
    today_appointments = [b for b in all_bookings if b["status"] == STATUS_APPROVED and b["date"] == today]
    stats = get_booking_stats(all_bookings)
    vehicles_in_garage = [booking for booking in all_bookings if booking.get("status") == STATUS_IN_GARAGE]

    return render_template(
        "admin.html",
        vehicles_in_garage=vehicles_in_garage,
        total_bookings=stats["total"],
        pending_count=stats["pending"],
        approved_count=stats["approved"],
        completed_count=stats["completed"],
        rejected_count=stats["rejected"],
        today_approved=today_appointments,
        today_appointments=today_appointments,
        last_7_days_data=_build_last_7_days_data(all_bookings),
        filters=filters,
        today=today,
        today_display=format_date_display(today),
        verified_checkin_booking=booking_data,
        booking_data=booking_data,
        checkin_booking_id=checkin_booking_id,
    )


def _render_checkin_page(booking_data=None, checkin_booking_id=""):
    today = get_today_date_string()
    all_bookings = get_admin_bookings()
    today_queue = [
        booking
        for booking in all_bookings
        if booking.get("status") == STATUS_APPROVED and booking.get("date") == today
    ]
    vehicles_in_garage = [
        booking
        for booking in all_bookings
        if booking.get("status") == STATUS_IN_GARAGE
    ]

    return render_template(
        "checkin.html",
        today=today,
        today_display=format_date_display(today),
        today_queue=today_queue,
        vehicles_in_garage=vehicles_in_garage,
        booking_data=booking_data,
        verified_booking=booking_data,
        checkin_booking_id=checkin_booking_id,
    )


@admin_bp.route("/admin")
def admin_dashboard():
    if not _require_admin():
        return redirect(url_for("main.home"))

    checkin_booking_id = request.args.get("checkin_booking_id", "").strip().upper()
    booking_data = None

    if checkin_booking_id:
        booking_data = get_booking_by_id(checkin_booking_id)
        if not booking_data:
            flash("Booking not found", "danger")

    return _render_admin_dashboard(booking_data=booking_data, checkin_booking_id=checkin_booking_id)


@admin_bp.route("/admin/slots")
def admin_slots():
    if not _require_admin():
        return redirect(url_for("main.home"))

    slots = {
        date: {
            **slot,
            "formatted_date": format_date_display(date),
        }
        for date, slot in get_slots_for_admin().items()
    }
    return render_template("admin_slots.html", slots=slots, today=get_today_date_string())


@admin_bp.route("/admin/bookings")
def admin_bookings():
    if not _require_admin():
        return redirect(url_for("main.home"))

    filters = {
        "date": request.args.get("date", "").strip(),
        "status": request.args.get("status", "").strip(),
    }
    bookings = get_admin_bookings(filters)
    today = get_today_date_string()
    return render_template("admin_bookings.html", bookings=bookings, filters=filters, today=today)


@admin_bp.route("/admin/walkin", methods=["GET", "POST"])
def admin_walkin():
    if not _require_admin():
        return redirect(url_for("main.home"))

    today = get_today_date_string()

    if request.method == "POST":
        customer_id = request.form.get("customer_id", "").strip().upper()
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        vehicle = request.form.get("vehicle", "").strip().upper()
        brand_model = request.form.get("brand_model", "").strip()
        service = request.form.get("service", "").strip()
        date = request.form.get("date", "").strip() or today

        if not all([vehicle, brand_model, service]) or (not customer_id and not all([name, phone])):
            flash("Please fill all manual entry fields", "danger")
        else:
            success, message, booking = create_manual_booking_with_customer(
                customer_id, name, phone, vehicle, brand_model, service, date,
            )
            if not success:
                flash(message, "danger")
            else:
                flash(f'Walk-in vehicle added to garage as {booking["booking_id"]}', "success")
                return redirect(url_for("admin.admin_walkin"))

    return render_template("admin_walkin.html", today=today)


@admin_bp.route("/admin/export")
def admin_export():
    if not _require_admin():
        return redirect(url_for("main.home"))

    return render_template("admin_export.html", today=get_today_date_string())


@admin_bp.route("/admin/search-customer")
def search_customer():
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 403

    query = request.args.get("q", "").strip()
    results = [
        {
            "customer_id": customer.get("id", ""),
            "id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
            "vehicle": customer.get("vehicle", ""),
        }
        for customer in search_customers(query, limit=8)
    ]
    return jsonify(results)


@admin_bp.route("/admin/add-customer", methods=["POST"])
def add_customer():
    if not _require_admin():
        return jsonify({"success": False, "error": "unauthorized"}), 403

    payload = request.get_json(silent=True) or request.form
    name = payload.get("name", "").strip()
    phone = normalize_phone(payload.get("phone", "").strip())
    vehicle = payload.get("vehicle", "").strip().upper()

    if not all([name, phone, vehicle]):
        return jsonify({"success": False, "error": "Name, phone, and vehicle are required."}), 400
    if len(phone) != 10:
        return jsonify({"success": False, "error": "Phone number must be exactly 10 digits."}), 400

    try:
        customer = ensure_customer(phone, name, vehicle)
    except Exception as error:
        get_db().rollback()
        log_action("ADD CUSTOMER ERROR", str(error))
        return jsonify({"success": False, "error": "Customer could not be saved right now."}), 500

    return jsonify(
        {
            "success": True,
            "customer": {
                "customer_id": customer.get("id", ""),
                "id": customer.get("id", ""),
                "name": customer.get("name", ""),
                "phone": customer.get("phone", ""),
                "vehicle": customer.get("vehicle", ""),
            },
        }
    )


@admin_bp.route("/checkin")
@admin_bp.route("/admin/checkin")
def admin_checkin_page():
    if not _require_admin():
        return redirect(url_for("main.home"))

    checkin_booking_id = request.args.get("checkin_booking_id", "").strip().upper()
    booking_data = get_booking_by_id(checkin_booking_id) if checkin_booking_id else None
    if checkin_booking_id and not booking_data:
        flash("Booking not found", "danger")
    return _render_checkin_page(booking_data=booking_data, checkin_booking_id=checkin_booking_id)


@admin_bp.route("/admin/checkin/verify", methods=["POST"])
def verify_checkin_booking():
    if not _require_admin():
        return redirect(url_for("main.home"))

    booking_id = request.form.get("booking_id", "").strip().upper()
    if not booking_id:
        flash("Booking ID is required", "danger")
        return _render_checkin_page()

    booking_data = get_booking_by_id(booking_id)
    if not booking_data:
        flash("Booking not found", "danger")

    return _render_checkin_page(booking_data=booking_data, checkin_booking_id=booking_id)


@admin_bp.route("/export/bookings")
def export_bookings():
    if not _require_admin():
        return redirect(url_for("main.home"))

    bookings = get_admin_bookings()
    rows = [
        [
            _normalize_csv_value(booking.get("booking_id", "")),
            _normalize_csv_value(booking.get("customer_id", "")),
            _normalize_csv_value(booking.get("name", "")),
            _normalize_csv_value(booking.get("phone", "")),
            _normalize_csv_value(booking.get("vehicle", "")),
            _normalize_csv_value(booking.get("service", "")),
            _format_csv_date(booking.get("date", "")),
            _normalize_csv_value(booking.get("status", "")),
            _format_csv_datetime(booking.get("created_at", "")),
        ]
        for booking in bookings
    ]
    return _csv_response(
        "bookings.csv",
        ["booking_id", "customer_id", "name", "phone", "vehicle", "service", "date", "status", "created_at"],
        rows,
    )


@admin_bp.route("/export/garage")
def export_garage():
    if not _require_admin():
        return redirect(url_for("main.home"))

    bookings = [booking for booking in get_admin_bookings() if booking.get("status") == STATUS_IN_GARAGE]
    rows = [
        [
            _normalize_csv_value(booking.get("booking_id", "")),
            _normalize_csv_value(booking.get("name", "")),
            _normalize_csv_value(booking.get("phone", "")),
            _normalize_csv_value(booking.get("vehicle", "")),
            _normalize_csv_value(booking.get("service", "")),
            _format_csv_date(booking.get("date", "")),
            _format_csv_datetime(booking.get("checked_in_at", "")),
        ]
        for booking in bookings
    ]
    return _csv_response(
        "garage_data.csv",
        ["booking_id", "name", "phone", "vehicle", "service", "date", "checked_in_at"],
        rows,
    )


@admin_bp.route("/admin/set-slots", methods=["POST"])
def set_slots():
    if not _require_admin():
        return redirect(url_for("main.home"))

    date = request.form.get("date", "").strip()
    slots_value = request.form.get("slots", "").strip()

    if not date or not slots_value:
        flash("Date and slots are required", "danger")
        return redirect(url_for("admin.admin_slots"))

    try:
        total_slots = int(slots_value)
    except ValueError:
        flash("Slots must be a valid number", "danger")
        return redirect(url_for("admin.admin_slots"))

    if total_slots < 0:
        flash("Slots cannot be negative", "danger")
        return redirect(url_for("admin.admin_slots"))

    if not set_slot_total(date, total_slots):
        flash("Cannot reduce slots below booked count", "danger")
        return redirect(url_for("admin.admin_slots"))

    flash("Slots updated successfully", "success")
    return redirect(url_for("admin.admin_slots"))


@admin_bp.route("/admin/approve/<booking_id>")
def approve_booking(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    booking = get_booking_by_id(booking_id)
    if not booking:
        flash("Booking not found", "error")
        return redirect(url_for("admin.admin_dashboard"))

    success, message, _updated_booking = approve_booking_service(booking_id)
    if not success:
        flash(message, "info" if booking.get("status") == STATUS_APPROVED else "danger")
        return redirect(url_for("admin.admin_dashboard"))

    booking = get_booking_by_id(booking_id)
    return _redirect_with_whatsapp(
        booking_id,
        booking,
        redirect(url_for("admin.admin_dashboard")),
    )


@admin_bp.route("/admin/reject/<booking_id>")
def reject_booking(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    success, message, _booking = reject_booking_service(booking_id)
    if not success:
        flash(message, "danger")
        return redirect(url_for("admin.admin_dashboard"))

    booking = get_booking_by_id(booking_id)
    fallback_response = redirect(url_for("admin.admin_dashboard"))
    notification_response = _redirect_with_whatsapp(booking_id, booking, fallback_response)
    if notification_response is fallback_response:
        flash("Booking Rejected", "danger")
    return notification_response


@admin_bp.route("/admin/checkin/<booking_id>")
def admin_checkin_booking(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    success, message, booking = checkin_vehicle(booking_id, get_today_date_string())
    if not success:
        flash(message, "danger")
        booking_data = get_booking_by_id(booking_id) if success else enrich_booking(booking)
        return _render_checkin_page(booking_data=booking_data, checkin_booking_id=booking_id)

    booking = get_booking_by_id(booking_id)
    fallback_response = _render_checkin_page(booking_data=booking, checkin_booking_id=booking_id)
    notification_response = _redirect_with_whatsapp(booking_id, booking, fallback_response)
    if notification_response is fallback_response:
        flash("Vehicle checked-in successfully", "success")
    return notification_response


@admin_bp.route("/admin/complete/<booking_id>")
def complete_booking(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    admin_id = session.get("user", {}).get("id", "unknown")
    booking = get_booking_by_id(booking_id)
    if not booking:
        flash("Booking not found", "error")
        return redirect(url_for("admin.admin_dashboard"))

    if booking.get("status") != STATUS_IN_GARAGE:
        flash("Only checked-in vehicles can be marked complete", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    success, message, _updated_booking = complete_booking_by_id(booking_id, performed_by=admin_id)
    if not success:
        flash(message, "error")
        return redirect(url_for("admin.admin_dashboard"))

    booking = get_booking_by_id(booking_id)
    fallback_response = redirect(url_for("admin.admin_dashboard"))
    notification_response = _redirect_with_whatsapp(booking_id, booking, fallback_response)
    if notification_response is fallback_response:
        flash("Vehicle marked completed", "success")
    return notification_response
