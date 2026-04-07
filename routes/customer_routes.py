from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models.customer_model import get_customer_by_id
from services.booking_service import create_booking_for_customer, get_customer_dashboard_data
from services.slot_service import get_next_14_days


customer_bp = Blueprint("customer", __name__)


@customer_bp.route("/dashboard")
def dashboard():
    if "customer_id" not in session or session.get("role") != "customer":
        flash("Please login as customer first", "error")
        return redirect(url_for("auth.login"))

    customer = get_customer_by_id(session["customer_id"]) or {
        "id": session["customer_id"],
        "name": session["name"],
    }
    dashboard_data = get_customer_dashboard_data(session["customer_id"])

    return render_template(
        "dashboard.html",
        customer=customer,
        bookings=dashboard_data["bookings"],
        past_bookings=dashboard_data["bookings"],
        due_for_service=dashboard_data["due_for_service"],
        latest_completed_booking=dashboard_data["latest_completed_booking"],
        date_slots=get_next_14_days(),
    )


@customer_bp.route("/verify-customer", methods=["GET", "POST"])
def verify_customer():
    flash("Customer verification flow has been disabled. Please book directly from your dashboard.", "info")
    if session.get("role") == "customer":
        return redirect(url_for("customer.dashboard"))
    return redirect(url_for("customer.book"))


@customer_bp.route("/book", methods=["GET", "POST"])
def book():
    if "customer_id" not in session or session.get("role") != "customer":
        flash("Please login first", "error")
        return redirect(url_for("auth.login"))

    if request.method == "GET":
        return redirect(url_for("customer.dashboard"))

    vehicle = request.form.get("vehicle_number", "").strip().upper()
    brand_model = request.form.get("brand_model", "").strip()
    service = request.form.get("service", "").strip()
    date = request.form.get("date", "").strip()
    customer_phone = request.form.get("customer_phone", "").strip()

    success, message, booking = create_booking_for_customer(
        session["customer_id"],
        session["name"],
        customer_phone,
        vehicle,
        brand_model,
        service,
        date,
    )
    if not success:
        flash(message, "danger")
        return redirect(url_for("customer.dashboard"))

    flash(f'Booking confirmed successfully! Booking ID: {booking["booking_id"]}', "success")
    return redirect(url_for("customer.dashboard"))
