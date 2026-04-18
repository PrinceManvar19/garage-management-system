import csv
import zipfile
from datetime import datetime, timedelta
from io import BytesIO, StringIO
from urllib.parse import quote

from flask import Blueprint, jsonify, Response, flash, redirect, render_template, request, session, url_for

from models.db import get_db
from services.booking_service import (
    approve_booking as approve_booking_service,
    checkin_vehicle,
    complete_booking_by_id,
    create_manual_booking_with_customer,
    enrich_booking,
    get_admin_bookings,
    get_booking_by_id,
    get_booking_stats,
    mark_whatsapp_sent,
    reject_booking as reject_booking_service,
)
from services.slot_service import get_slots_for_admin, set_slot_total
from utils.constants import STATUS_APPROVED, STATUS_IN_GARAGE, STATUS_COMPLETED, STATUS_PENDING, STATUS_REJECTED
from models.customer_model import (
    add_vehicle_to_customer,
    ensure_customer,
    get_customer_by_id,
    get_customer_by_phone,
    get_customer_with_vehicles,
    search_customers,
)
from utils.helpers import format_date_display, format_datetime_display, get_today_date_string, normalize_phone


admin_bp = Blueprint("admin", __name__)


def _require_admin():
    return session.get("role") == "admin"


def _build_whatsapp_message(booking):
    status_labels = {
        STATUS_PENDING: "Pending",
        STATUS_APPROVED: "Approved",
        STATUS_IN_GARAGE: "Checked-In",
        STATUS_REJECTED: "Rejected",
        STATUS_COMPLETED: "Completed",
    }
    status = booking.get("status")
    return (
        f"Hello {booking.get('name', '')}\n\n"
        f"Booking ID: {booking.get('booking_id', '')}\n"
        f"Service: {booking.get('service', '')}\n"
        f"Vehicle: {booking.get('vehicle', '')}\n"
        f"Date: {booking.get('date', '')}\n"
        f"Status: {status_labels.get(status, (status or '').title())}\n\n"
        "Thank you - Shreeji Auto Services"
    )


def _csv_response(filename, headers, rows):
    return Response(
        _csv_string(headers, rows),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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


# CHANGED: Shared admin page/export helpers for the sidebar split.
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


def _build_export_response(data_type, from_date="", to_date="", status=""):
    if data_type == "bookings":
        rows = _fetch_booking_export_rows(from_date, to_date, status)
        return _csv_response("bookings.csv", BOOKING_EXPORT_HEADERS, _booking_csv_rows(rows))

    if data_type == "customers":
        rows = _fetch_customer_export_rows()
        return _csv_response("customers.csv", CUSTOMER_EXPORT_HEADERS, _customer_csv_rows(rows))

    if data_type == "garage":
        rows = _fetch_booking_export_rows(from_date, to_date, garage_only=True)
        return _csv_response("garage_data.csv", GARAGE_EXPORT_HEADERS, _garage_csv_rows(rows))

    if data_type == "all":
        booking_rows = _fetch_booking_export_rows(from_date, to_date, status)
        customer_rows = _fetch_customer_export_rows()
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(
                "bookings.csv",
                _csv_string(BOOKING_EXPORT_HEADERS, _booking_csv_rows(booking_rows)),
            )
            zip_file.writestr(
                "customers.csv",
                _csv_string(CUSTOMER_EXPORT_HEADERS, _customer_csv_rows(customer_rows)),
            )
        zip_buffer.seek(0)
        return Response(
            zip_buffer.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition": 'attachment; filename="admin_data_export.zip"'},
        )

    return None


def _handle_walkin_submission(form, default_date):
    customer_id = form.get("customer_id", "").strip().upper()
    name = form.get("name", "").strip()
    phone = form.get("phone", "").strip()
    vehicle = (
        form.get("vehicle_number", "").strip().upper()
        or form.get("vehicle", "").strip().upper()
    )
    vehicle_brand = form.get("vehicle_brand", "").strip()
    vehicle_model = form.get("vehicle_model", "").strip()
    brand_model = form.get("brand_model", "").strip()
    service = form.get("service", "").strip()
    date = form.get("date", "").strip() or default_date

    if not all([vehicle, brand_model, service]) or not all([name, phone]):
        return False, "Please fill all manual entry fields", None

    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return False, "Phone number must be exactly 10 digits.", None

    customer = get_customer_by_id(customer_id) if customer_id else None
    if not customer:
        customer = get_customer_by_phone(normalized_phone)

    if customer:
        customer_id = customer.get("id", "")
        name = customer.get("name", name)
        phone = customer.get("phone", normalized_phone)
    else:
        customer = ensure_customer(normalized_phone, name, vehicle, vehicle_brand, vehicle_model)
        customer_id = customer.get("id", "")
        name = customer.get("name", name)
        phone = customer.get("phone", normalized_phone)

    return create_manual_booking_with_customer(
        customer_id,
        name,
        phone,
        vehicle,
        brand_model,
        service,
        date,
    )


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


# CHANGED: Shared renderer for /checkin and /admin/checkin/verify.
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


# CHANGED: Sidebar page for slot management.
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


# CHANGED: Sidebar page for booking request management.
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


# CHANGED: Sidebar page for walk-in customer lookup and garage entry.
@admin_bp.route("/admin/walkin", methods=["GET", "POST"])
def admin_walkin():
    if not _require_admin():
        return redirect(url_for("main.home"))

    today = get_today_date_string()

    if request.method == "POST":
        success, message, booking = _handle_walkin_submission(request.form, today)
        if not success:
            flash(message, "danger")
        else:
            flash(f'Walk-in vehicle added to garage as {booking["booking_id"]}', "success")
            return redirect(url_for("admin.admin_walkin"))

    return render_template("admin_walkin.html", today=today)


# CHANGED: Sidebar page for filtered CSV/ZIP exports.
@admin_bp.route("/admin/export")
def admin_export():
    if not _require_admin():
        return redirect(url_for("main.home"))

    return render_template("admin_export.html", today=get_today_date_string())


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

    return _build_export_response("bookings")


@admin_bp.route("/export/garage")
def export_garage():
    if not _require_admin():
        return redirect(url_for("main.home"))

    return _build_export_response("garage")


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

    flash("Booking Approved", "success")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/reject/<booking_id>")
def reject_booking(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    success, message, _booking = reject_booking_service(booking_id)
    flash(message if not success else "Booking Rejected", "error" if not success else "danger")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/checkin/<booking_id>")
def admin_checkin_booking(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    success, message, booking = checkin_vehicle(booking_id, get_today_date_string())
    flash(message if not success else "Vehicle checked-in successfully", "danger" if not success else "success")
    booking_data = get_booking_by_id(booking_id) if success else (enrich_booking(booking) if booking else None)
    return _render_checkin_page(booking_data=booking_data, checkin_booking_id=booking_id)


@admin_bp.route("/admin/whatsapp/<booking_id>")
def send_booking_whatsapp(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    booking = get_booking_by_id(booking_id)
    if not booking:
        flash("Booking not found", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    if booking.get("status") not in {STATUS_PENDING, STATUS_APPROVED, STATUS_IN_GARAGE, STATUS_REJECTED, STATUS_COMPLETED}:
        flash("WhatsApp is not available for this booking", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    phone = normalize_phone(booking.get("phone", ""))
    if not phone:
        flash("Customer phone number is not available", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    success, message, _updated_booking = mark_whatsapp_sent(booking_id)
    if not success:
        flash(message, "danger")
        return redirect(url_for("admin.admin_dashboard"))

    whatsapp_url = f"https://wa.me/91{phone}?text={quote(_build_whatsapp_message(booking))}"
    return redirect(whatsapp_url)


@admin_bp.route("/admin/export-data")
def export_data():
    if not _require_admin():
        return redirect(url_for("main.home"))

    return _build_export_response("all")


@admin_bp.route("/checkin", methods=["GET", "POST"])
def checkin():
    if not _require_admin():
        return redirect(url_for("main.home"))

    today = get_today_date_string()
    verified_booking = None
    checkin_booking_id = request.args.get("checkin_booking_id", "").strip().upper()

    if request.method == "GET" and checkin_booking_id:
        verified_booking = get_booking_by_id(checkin_booking_id)
        if not verified_booking:
            flash("Booking not found", "danger")

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        booking_id = request.form.get("booking_id", "").strip().upper()
        checkin_booking_id = booking_id

        if action == "verify_booking":
            booking = get_booking_by_id(booking_id)
            if not booking:
                flash("Invalid Booking ID", "danger")
            else:
                verified_booking = enrich_booking(booking)
                if booking.get("date") != today:
                    flash("This booking is not scheduled for today", "danger")
                elif booking.get("status") != STATUS_APPROVED:
                    flash("Booking must be approved before check-in", "danger")

        elif action == "checkin_vehicle":
            success, message, booking = checkin_vehicle(booking_id, today)
            if not success:
                verified_booking = enrich_booking(booking) if booking else None
                flash(message, "danger")
            else:
                verified_booking = enrich_booking(booking)
                flash("Vehicle checked-in successfully", "success")

        elif action == "manual_entry":
            success, message, booking = _handle_walkin_submission(request.form, today)
            if not success:
                flash(message, "danger")
            else:
                verified_booking = enrich_booking(booking)
                flash(f'Walk-in vehicle added to garage as {booking["booking_id"]}', "success")

    return _render_checkin_page(booking_data=verified_booking, checkin_booking_id=checkin_booking_id)


@admin_bp.route("/admin/find-customer")
def find_customer():
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 403

    phone = normalize_phone(request.args.get("phone", "").strip())
    customer = get_customer_by_phone(phone)
    if customer:
        return jsonify({
            "found": True,
            "name": customer.get("name", ""),
            "vehicle": customer.get("vehicle", ""),
            "phone": customer.get("phone", ""),
            "customer_id": customer.get("id", "")
        })
    return jsonify({"found": False})


@admin_bp.route("/admin/get-vehicles")
def admin_get_vehicles():
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 403

    phone = normalize_phone(request.args.get("phone", "").strip())
    customer_id = request.args.get("customer_id", "").strip().upper()
    identifier = phone or customer_id

    if not identifier:
        return jsonify({"found": False, "customer": None, "vehicles": []}), 400

    lookup = get_customer_with_vehicles(identifier)
    if not lookup:
        return jsonify({"found": False, "customer": None, "vehicles": []})

    customer = lookup["customer"]
    vehicles = [
        {
            "plate": vehicle.get("plate_number", ""),
            "plate_number": vehicle.get("plate_number", ""),
            "brand": vehicle.get("brand", ""),
            "model": vehicle.get("model", ""),
        }
        for vehicle in lookup["vehicles"]
    ]
    return jsonify({
        "found": True,
        "customer": {
            "id": customer.get("id", ""),
            "customer_id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
        },
        "vehicles": vehicles,
    })


@admin_bp.route("/admin/find-customer-by-id")
def find_customer_by_id():
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 403

    customer_id = request.args.get("customer_id", "").strip().upper()
    customer = get_customer_by_id(customer_id)
    if customer:
        return jsonify({
            "found": True,
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
            "vehicle": customer.get("vehicle", "")
        })
    return jsonify({"found": False})


# CHANGED: AJAX customer search for the walk-in page.
@admin_bp.route("/admin/search-customer")
def search_customer():
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 403

    query = request.args.get("q", "").strip()
    results = [
        {
            "customer_id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
            "vehicle": customer.get("vehicle", ""),
        }
        for customer in search_customers(query, limit=5)
    ]
    return jsonify(results)


# CHANGED: Shared JSON endpoint used by dashboard modal and walk-in registration.
@admin_bp.route("/admin/add-customer", methods=["POST"])
def add_customer():
    if not _require_admin():
        return jsonify({"success": False, "error": "unauthorized"}), 403

    payload = request.get_json(silent=True) or request.form
    name = payload.get("name", "").strip()
    phone = normalize_phone(payload.get("phone", "").strip())
    vehicle = payload.get("vehicle", "").strip().upper()
    brand = payload.get("brand", "").strip()
    model = payload.get("model", "").strip()

    if not all([name, phone, vehicle]):
        return jsonify({"success": False, "error": "Name, phone, and vehicle are required."}), 400
    if len(phone) != 10:
        return jsonify({"success": False, "error": "Phone number must be exactly 10 digits."}), 400

    try:
        customer = ensure_customer(phone, name, vehicle, brand, model)
    except Exception:
        get_db().rollback()
        return jsonify({"success": False, "error": "Customer could not be saved right now."}), 500

    return jsonify({
        "success": True,
        "customer": {
            "customer_id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
            "vehicle": customer.get("vehicle", ""),
        },
    })


@admin_bp.route("/admin/add-vehicle", methods=["POST"])
def admin_add_vehicle():
    if not _require_admin():
        return jsonify({"success": False, "error": "unauthorized"}), 403

    payload = request.get_json(silent=True) or request.form
    customer_id = payload.get("customer_id", "").strip().upper()
    phone = normalize_phone(payload.get("phone", "").strip())
    plate_number = (payload.get("plate_number") or payload.get("plate") or "").strip().upper()
    brand = payload.get("brand", "").strip()
    model = payload.get("model", "").strip()

    if not plate_number:
        return jsonify({"success": False, "error": "Vehicle number is required."}), 400
    if not brand:
        return jsonify({"success": False, "error": "Brand is required."}), 400

    customer = get_customer_by_id(customer_id) if customer_id else None
    if not customer and phone:
        customer = get_customer_by_phone(phone)
    if not customer:
        return jsonify({"success": False, "error": "Customer not found for this phone number."}), 400

    try:
        vehicle = add_vehicle_to_customer(customer.get("id", ""), plate_number, brand, model)
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400
    except Exception:
        get_db().rollback()
        return jsonify({"success": False, "error": "Vehicle could not be saved right now."}), 500

    lookup = get_customer_with_vehicles(customer.get("id", ""))
    vehicles = [
        {
            "plate": item.get("plate_number", ""),
            "plate_number": item.get("plate_number", ""),
            "brand": item.get("brand", ""),
            "model": item.get("model", ""),
        }
        for item in (lookup or {}).get("vehicles", [])
    ]

    return jsonify({
        "success": True,
        "customer": {
            "id": customer.get("id", ""),
            "customer_id": customer.get("id", ""),
            "name": customer.get("name", ""),
            "phone": customer.get("phone", ""),
        },
        "vehicle": {
            "plate": vehicle.get("plate_number", ""),
            "plate_number": vehicle.get("plate_number", ""),
            "brand": vehicle.get("brand", ""),
            "model": vehicle.get("model", ""),
        },
        "vehicles": vehicles,
    })


# CHANGED: Lightweight export count preview for the new export page.
@admin_bp.route("/admin/export-preview")
def export_preview():
    if not _require_admin():
        return jsonify({"error": "unauthorized"}), 403

    data_type = request.args.get("data_type", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    status = request.args.get("status", "").strip()

    if data_type == "bookings":
        count = _count_booking_exports(from_date, to_date, status)
    elif data_type == "customers":
        row = get_db().execute("SELECT COUNT(*) AS total FROM customers").fetchone()
        count = row["total"] if row else 0
    elif data_type == "garage":
        count = _count_booking_exports(from_date, to_date, garage_only=True)
    elif data_type == "all":
        customer_row = get_db().execute("SELECT COUNT(*) AS total FROM customers").fetchone()
        booking_count = _count_booking_exports(from_date, to_date, status)
        count = booking_count + (customer_row["total"] if customer_row else 0)
    else:
        return jsonify({"count": 0})

    return jsonify({"count": count})


# CHANGED: Filtered CSV/ZIP download endpoint for /admin/export.
@admin_bp.route("/export/download")
def export_download():
    if not _require_admin():
        return redirect(url_for("main.home"))

    data_type = request.args.get("data_type", "").strip()
    from_date = request.args.get("from_date", "").strip()
    to_date = request.args.get("to_date", "").strip()
    status = request.args.get("status", "").strip()

    if not data_type:
        return "data_type is required", 400

    response = _build_export_response(data_type, from_date, to_date, status)
    if response is None:
        return "Invalid data_type", 400
    return response


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

    flash("Vehicle marked completed", "success")
    return redirect(url_for("admin.admin_dashboard"))
