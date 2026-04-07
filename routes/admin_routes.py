from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from services.booking_service import (
    approve_booking as approve_booking_service,
    checkin_vehicle,
    complete_booking_by_id,
    create_manual_booking,
    enrich_booking,
    get_admin_bookings,
    get_booking_by_id,
    get_booking_stats,
    reject_booking as reject_booking_service,
)
from services.slot_service import get_slots_for_admin, set_slot_total
from utils.constants import STATUS_APPROVED, STATUS_CHECKED_IN
from utils.helpers import get_today_date_string


admin_bp = Blueprint("admin", __name__)


def _require_admin():
    return session.get("role") == "admin"


@admin_bp.route("/admin")
def admin_dashboard():
    if not _require_admin():
        return redirect(url_for("main.home"))

    filters = {
        "query": request.args.get("query", ""),
        "date": request.args.get("date", ""),
        "status": request.args.get("status", ""),
    }
    all_bookings = get_admin_bookings()
    bookings = get_admin_bookings(filters)
    stats = get_booking_stats(all_bookings)
    vehicles_in_garage = [booking for booking in all_bookings if booking.get("status") == STATUS_CHECKED_IN]

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
            elif booking.get("date") != today:
                flash("This booking is not scheduled for today", "danger")
            elif booking.get("status") != STATUS_APPROVED:
                flash("Booking must be approved before check-in", "danger")
            else:
                verified_booking = enrich_booking(booking)

        elif action == "checkin_vehicle":
            success, message, booking = checkin_vehicle(booking_id, today)
            if not success:
                flash(message, "danger")
            else:
                verified_booking = enrich_booking(booking)
                flash("Vehicle checked-in successfully", "success")

        elif action == "manual_entry":
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            vehicle = request.form.get("vehicle", "").strip().upper()
            brand_model = request.form.get("brand_model", "").strip()
            service = request.form.get("service", "").strip()

            if not all([name, phone, vehicle, brand_model, service]):
                flash("Please fill all manual entry fields", "danger")
            else:
                success, message, booking = create_manual_booking(name, phone, vehicle, brand_model, service, today)
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
