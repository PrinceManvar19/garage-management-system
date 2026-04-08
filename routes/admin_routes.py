import csv
from io import StringIO
from urllib.parse import quote

from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

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
    normalize_phone,
    reject_booking as reject_booking_service,
)
from services.slot_service import get_slots_for_admin, set_slot_total
from utils.constants import STATUS_APPROVED, STATUS_CHECKED_IN, STATUS_COMPLETED, STATUS_REJECTED
from utils.helpers import get_today_date_string


admin_bp = Blueprint("admin", __name__)


def _require_admin():
    return session.get("role") == "admin"


def _build_whatsapp_message(booking):
    status_labels = {
        STATUS_APPROVED: "Approved",
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
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_bp.route("/admin")
def admin_dashboard():
    if not _require_admin():
        return redirect(url_for("main.home"))

    filters = {
        "query": request.args.get("query", ""),
        "date": request.args.get("date", ""),
        "status": request.args.get("status", ""),
    }
    today = get_today_date_string()
    all_bookings = get_admin_bookings()
    bookings = get_admin_bookings(filters)
    stats = get_booking_stats(all_bookings)
    vehicles_in_garage = [booking for booking in all_bookings if booking.get("status") == STATUS_CHECKED_IN]
    checkin_booking_id = request.args.get("checkin_booking_id", "").strip().upper()
    verified_checkin_booking = None

    if checkin_booking_id:
        verified_checkin_booking = get_booking_by_id(checkin_booking_id)
        if not verified_checkin_booking:
            flash("Booking not found", "danger")

    return render_template(
        "admin.html",
        bookings=bookings,
        slots=get_slots_for_admin(),
        vehicles_in_garage=vehicles_in_garage,
        total_bookings=stats["total"],
        pending_count=stats["pending"],
        approved_count=stats["approved"],
        completed_count=stats["completed"],
        rejected_count=stats["rejected"],
        filters=filters,
        today=today,
        verified_checkin_booking=verified_checkin_booking,
        checkin_booking_id=checkin_booking_id,
    )


@admin_bp.route("/admin/checkin/verify", methods=["POST"])
def verify_checkin_booking():
    if not _require_admin():
        return redirect(url_for("main.home"))

    booking_id = request.form.get("booking_id", "").strip().upper()
    if not booking_id:
        flash("Booking ID is required", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    return redirect(url_for("admin.admin_dashboard", checkin_booking_id=booking_id))


@admin_bp.route("/export/bookings")
def export_bookings():
    if not _require_admin():
        return redirect(url_for("main.home"))

    bookings = get_admin_bookings()
    rows = [
        [
            booking.get("booking_id", ""),
            booking.get("customer_id", ""),
            booking.get("name", ""),
            booking.get("phone", ""),
            booking.get("vehicle", ""),
            booking.get("service", ""),
            booking.get("date", ""),
            booking.get("status", ""),
            booking.get("created_at", ""),
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

    bookings = [booking for booking in get_admin_bookings() if booking.get("status") == STATUS_CHECKED_IN]
    rows = [
        [
            booking.get("booking_id", ""),
            booking.get("name", ""),
            booking.get("phone", ""),
            booking.get("vehicle", ""),
            booking.get("service", ""),
            booking.get("date", ""),
            booking.get("checked_in_at", ""),
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
        return redirect(url_for("admin.admin_dashboard"))

    try:
        total_slots = int(slots_value)
    except ValueError:
        flash("Slots must be a valid number", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    if total_slots < 0:
        flash("Slots cannot be negative", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    if not set_slot_total(date, total_slots):
        flash("Cannot reduce slots below booked count", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    flash("Slots updated successfully", "success")
    return redirect(url_for("admin.admin_dashboard"))


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

    success, message, _booking = checkin_vehicle(booking_id, get_today_date_string())
    flash(message if not success else "Vehicle checked-in successfully", "danger" if not success else "success")
    return redirect(url_for("admin.admin_dashboard"))


@admin_bp.route("/admin/whatsapp/<booking_id>")
def send_booking_whatsapp(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    booking = get_booking_by_id(booking_id)
    if not booking:
        flash("Booking not found", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    if booking.get("status") not in {STATUS_APPROVED, STATUS_REJECTED, STATUS_COMPLETED}:
        flash("WhatsApp is available only for approved, rejected, or completed bookings", "danger")
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


@admin_bp.route("/checkin", methods=["GET", "POST"])
def checkin():
    if not _require_admin():
        return redirect(url_for("main.home"))

    today = get_today_date_string()
    verified_booking = None

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        booking_id = request.form.get("booking_id", "").strip().upper()

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
            customer_id = request.form.get("customer_id", "").strip().upper()
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            vehicle = request.form.get("vehicle", "").strip().upper()
            brand_model = request.form.get("brand_model", "").strip()
            service = request.form.get("service", "").strip()

            if not all([vehicle, brand_model, service]) or (not customer_id and not all([name, phone])):
                flash("Please fill all manual entry fields", "danger")
            else:
                success, message, booking = create_manual_booking_with_customer(
                    customer_id,
                    name,
                    phone,
                    vehicle,
                    brand_model,
                    service,
                    today,
                )
                if not success:
                    flash(message, "danger")
                else:
                    verified_booking = enrich_booking(booking)
                    flash(f'Walk-in vehicle added to garage as {booking["booking_id"]}', "success")

    vehicles_in_garage = [booking for booking in get_admin_bookings() if booking.get("status") == STATUS_CHECKED_IN]
    return render_template(
        "checkin.html",
        today=today,
        verified_booking=verified_booking,
        vehicles_in_garage=vehicles_in_garage,
    )


@admin_bp.route("/admin/complete/<booking_id>")
def complete_booking(booking_id):
    if not _require_admin():
        return redirect(url_for("main.home"))

    booking = get_booking_by_id(booking_id)
    if not booking:
        flash("Booking not found", "error")
        return redirect(url_for("admin.admin_dashboard"))

    if booking.get("status") != STATUS_CHECKED_IN:
        flash("Only checked-in vehicles can be marked complete", "danger")
        return redirect(url_for("admin.admin_dashboard"))

    success, message, _updated_booking = complete_booking_by_id(booking_id)
    if not success:
        flash(message, "error")
        return redirect(url_for("admin.admin_dashboard"))

    flash("Vehicle marked completed", "success")
    return redirect(url_for("admin.admin_dashboard"))
