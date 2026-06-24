import hmac
import os
from urllib.parse import quote

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from db_neon import get_neon_db as get_db
from models.booking_model import count_bookings_for_slot, update_message_flags
from models.customer_model import ensure_customer, get_customer_by_id, get_customer_by_phone
from models.slot_model import update_slot
from services.auth_service import login_user_by_identifier, set_user_session
from services.booking_service import (
    approve_booking as approve_booking_service,
    build_whatsapp_message,
    checkin_vehicle,
    complete_booking_by_id,
    create_manual_booking_with_customer,
    get_admin_bookings_local,
    get_booking_by_id,
    get_booking_stats,
    normalize_phone,
    reject_booking as reject_booking_service,
)
from services.slot_service import get_slots_for_admin_local, set_slot_total
from utils.constants import STATUS_APPROVED, STATUS_CHECKED_IN
from utils.helpers import format_date_display, get_today_date_string, log_action


web_admin_bp = Blueprint("web_admin", __name__, url_prefix="/admin")


def _refresh_cache(booking_id):
    """Refresh a single booking in the local cache after a write to Neon."""
    import threading
    from flask import current_app
    from services.cache_sync import update_booking_in_cache

    app = current_app._get_current_object()
    threading.Thread(
        target=update_booking_in_cache,
        args=(booking_id, app),
        daemon=True,
    ).start()


def _refresh_cache_if_stale():
    """Trigger a background cache sync if cache is older than 90 seconds."""
    import threading
    import time
    from flask import current_app
    import services.cache_sync as cache_sync

    age = time.time() - cache_sync._last_sync_time
    if age > 90:
        app = current_app._get_current_object()
        threading.Thread(
            target=cache_sync.sync_now,
            args=(app,),
            daemon=True,
        ).start()


def _require_web_admin():
    if session.get("role") != "admin":
        flash("Admin access required", "error")
        return redirect(url_for("web_admin.web_admin_login"))
    return None


def _web_admin_pin():
    return os.getenv("WEB_ADMIN_PIN", "").strip()


def _web_admin_pin_valid(submitted_pin):
    configured_pin = _web_admin_pin()
    if not configured_pin:
        return True
    return hmac.compare_digest((submitted_pin or "").strip(), configured_pin)


def _get_current_user_id():
    return session.get("user", {}).get("id") or session.get("admin_id") or "unknown"


def _get_whatsapp_url(booking_id, booking):
    if not booking:
        return None

    whatsapp_message, flags = build_whatsapp_message(booking)
    phone = normalize_phone(booking.get("phone", ""))
    if not whatsapp_message or not phone:
        return None

    try:
        if flags:
            update_message_flags(booking_id, **flags)
            get_db().commit()
    except Exception as error:
        get_db().rollback()
        log_action("DB ERROR UPDATE MSG FLAGS", f"{booking_id} - {error}")
        return None

    encoded = quote(whatsapp_message)
    return f"https://wa.me/91{phone}?text={encoded}"


def _redirect_with_whatsapp(booking_id, booking, fallback_response):
    whatsapp_url = _get_whatsapp_url(booking_id, booking)
    if not whatsapp_url:
        return fallback_response
    flash("WhatsApp message is ready to send.", "success")
    return redirect(whatsapp_url)


def _slots_for_template():
    return {
        date: {
            **slot,
            "formatted_date": format_date_display(date),
        }
        for date, slot in get_slots_for_admin_local().items()
    }


def _handle_walkin_submission(form, default_date, performed_by=None):
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
    direct_walkin = form.get("no_slot_walkin") == "on"
    slot_id = None if direct_walkin else form.get("slot_id", "").strip()
    date = (default_date if direct_walkin else (slot_id or form.get("date", "").strip())) or default_date

    if not all([name, phone, vehicle, brand_model, service]):
        return False, "Please fill all manual entry fields.", None

    normalized_phone = normalize_phone(phone)
    if len(normalized_phone) != 10:
        return False, "Phone number must be exactly 10 digits.", None

    customer = get_customer_by_id(customer_id) if customer_id else None
    if not customer:
        customer = get_customer_by_phone(normalized_phone)

    if customer:
        customer_id = customer.get("id", "")
        name = customer.get("name", name)
        phone = customer.get("phone", normalized_phone)
    else:
        try:
            customer = ensure_customer(normalized_phone, name, vehicle, vehicle_brand, vehicle_model)
        except Exception as error:
            get_db().rollback()
            log_action("WALKIN CUSTOMER ERROR", str(error))
            return False, "Customer could not be saved right now.", None

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
        performed_by=performed_by,
        slot_id=slot_id,
    )


@web_admin_bp.route("/login", methods=["GET", "POST"])
def web_admin_login():
    # Admin email OTP is temporarily disabled for now.
    session.pop("admin_otp", None)

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        try:
            user = login_user_by_identifier(identifier)
            if user and user["role"] == "admin":
                session.clear()
                set_user_session(user["id"], user["name"], user["role"], user.get("phone", ""))
                flash("Login successful!", "success")
                return redirect(url_for("web_admin.web_admin_dashboard"))
        except Exception as error:
            log_action("WEB ADMIN LOGIN ERROR", f"{identifier}: {error}")

        flash("Invalid admin credentials. Please check and try again.", "error")

    return render_template("web_admin_login.html")


@web_admin_bp.route("/logout")
def web_admin_logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for("web_admin.web_admin_login"))


@web_admin_bp.route("/")
def web_admin_dashboard():
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard
    _refresh_cache_if_stale()

    today = get_today_date_string()
    bookings = get_admin_bookings_local({})
    stats = get_booking_stats(bookings)
    vehicles_in_garage = [b for b in bookings if b.get("status") == STATUS_CHECKED_IN]
    today_appointments = [
        b for b in bookings
        if b.get("date") == today and b.get("status") == STATUS_APPROVED
    ]
    late_arrival_bookings = [
        b for b in bookings
        if b.get("status") == STATUS_APPROVED and b.get("date") != today
    ]

    return render_template(
        "web_admin_dashboard.html",
        stats=stats,
        vehicles_in_garage=vehicles_in_garage,
        today_appointments=today_appointments,
        late_arrival_bookings=late_arrival_bookings,
        today=today,
        today_display=format_date_display(today),
    )


@web_admin_bp.route("/slots")
def web_admin_slots():
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    return render_template(
        "web_admin_slots.html",
        slots=_slots_for_template(),
        today=get_today_date_string(),
    )


@web_admin_bp.route("/set-slots", methods=["POST"])
def web_admin_set_slots():
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    date = request.form.get("date", "").strip()
    slots_value = request.form.get("slots", "").strip()

    if not date or not slots_value:
        flash("Date and slots are required", "error")
        return redirect(url_for("web_admin.web_admin_slots"))

    try:
        total_slots = int(slots_value)
    except ValueError:
        flash("Slots must be a valid number", "error")
        return redirect(url_for("web_admin.web_admin_slots"))

    if total_slots < 0:
        flash("Slots cannot be negative", "error")
        return redirect(url_for("web_admin.web_admin_slots"))

    if not set_slot_total(date, total_slots):
        flash("Cannot reduce slots below booked count", "error")
        return redirect(url_for("web_admin.web_admin_slots"))

    flash("Slots updated successfully", "success")
    return redirect(url_for("web_admin.web_admin_slots"))


@web_admin_bp.route("/slots/<slot_id>/edit", methods=["POST"])
def web_admin_edit_slot(slot_id):
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    date = request.form.get("date", "").strip()
    time_value = request.form.get("time", "").strip()
    max_bookings_value = (
        request.form.get("max_bookings", "").strip()
        or request.form.get("slots", "").strip()
    )
    status = request.form.get("status", "open").strip().lower()
    booked_count = count_bookings_for_slot(slot_id)

    try:
        max_bookings = int(max_bookings_value)
    except ValueError:
        flash("Max bookings must be a valid number", "error")
        return redirect(url_for("web_admin.web_admin_slots"))

    if max_bookings < booked_count:
        flash("Cannot reduce slots below booked count", "error")
        return redirect(url_for("web_admin.web_admin_slots"))

    if status == "closed":
        max_bookings = booked_count

    result = update_slot(slot_id, date, time_value, max_bookings, status)
    if not result.get("success"):
        flash(result.get("error", "Slot could not be updated"), "error")
        return redirect(url_for("web_admin.web_admin_slots"))

    from flask import current_app
    from services.cache_sync import update_slot_in_cache

    app = current_app._get_current_object()
    update_slot_in_cache(result["slot"]["date"], app, old_slot_date=slot_id)

    flash("Slot updated successfully", "success")
    return redirect(url_for("web_admin.web_admin_slots"))


@web_admin_bp.route("/checkin")
def web_admin_checkin_page():
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard
    _refresh_cache_if_stale()

    today = get_today_date_string()
    all_relevant = get_admin_bookings_local({})
    today_queue = [
        b for b in all_relevant
        if b.get("date") == today and b.get("status") == STATUS_APPROVED
    ]
    vehicles_in_garage = [
        b for b in all_relevant
        if b.get("status") == STATUS_CHECKED_IN
    ]
    booking_id = request.args.get("booking_id", "").strip()
    booking_data = get_booking_by_id(booking_id) if booking_id else None

    return render_template(
        "web_admin_checkin.html",
        today=today,
        today_queue=today_queue,
        vehicles_in_garage=vehicles_in_garage,
        booking_data=booking_data,
        checkin_booking_id=booking_id,
    )


@web_admin_bp.route("/checkin/verify", methods=["POST"])
def web_admin_checkin_verify():
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    booking_id = request.form.get("booking_id", "").strip().upper()
    if booking_id:
        return redirect(url_for("web_admin.web_admin_checkin_page", booking_id=booking_id))

    flash("Please provide a booking ID.", "error")
    return redirect(url_for("web_admin.web_admin_checkin_page"))


@web_admin_bp.route("/checkin/<booking_id>", methods=["POST"])
def web_admin_checkin_booking(booking_id):
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    success, message, booking = checkin_vehicle(
        booking_id,
        get_today_date_string(),
        performed_by=_get_current_user_id(),
    )
    flash(message if not success else "Vehicle checked in successfully", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("web_admin.web_admin_checkin_page", booking_id=booking_id))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)


@web_admin_bp.route("/bookings")
def web_admin_bookings():
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard
    _refresh_cache_if_stale()

    filters = {
        "date": request.args.get("date", "").strip(),
        "status": request.args.get("status", "").strip(),
        "query": request.args.get("query", "").strip(),
    }
    bookings = get_admin_bookings_local(filters)
    return render_template(
        "web_admin_bookings.html",
        bookings=bookings,
        filters=filters,
        today=get_today_date_string(),
    )


@web_admin_bp.route("/approve/<booking_id>", methods=["POST"])
def web_admin_approve_booking(booking_id):
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    success, message, booking = approve_booking_service(
        booking_id,
        performed_by=_get_current_user_id(),
    )
    flash(message if not success else "Booking approved", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("web_admin.web_admin_bookings"))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)


@web_admin_bp.route("/reject/<booking_id>", methods=["POST"])
def web_admin_reject_booking(booking_id):
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    success, message, booking = reject_booking_service(
        booking_id,
        performed_by=_get_current_user_id(),
    )
    flash(message if not success else "Booking rejected", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("web_admin.web_admin_bookings"))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)


@web_admin_bp.route("/walkin", methods=["GET", "POST"])
def web_admin_walkin():
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    today = get_today_date_string()
    if request.method == "POST":
        success, message, booking = _handle_walkin_submission(
            request.form,
            today,
            performed_by=_get_current_user_id(),
        )
        if not success:
            flash(message, "error")
        else:
            flash(f'Walk-in vehicle added to garage as {booking["booking_id"]}', "success")
            _refresh_cache(booking["booking_id"])
            fallback = redirect(url_for("web_admin.web_admin_walkin"))
            return _redirect_with_whatsapp(booking["booking_id"], booking, fallback)

    return render_template("web_admin_walkin.html", today=today, slots=_slots_for_template())


@web_admin_bp.route("/find-customer")
def web_admin_find_customer():
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return jsonify({"error": "unauthorized"}), 403

    phone = normalize_phone(request.args.get("phone", "").strip())
    customer = get_customer_by_phone(phone)
    if not customer:
        return jsonify({"found": False})

    return jsonify({
        "found": True,
        "name": customer.get("name", ""),
        "vehicle": customer.get("vehicle", ""),
        "phone": customer.get("phone", ""),
        "customer_id": customer.get("id", ""),
    })


@web_admin_bp.route("/complete/<booking_id>", methods=["POST"])
def web_admin_complete_booking(booking_id):
    admin_guard = _require_web_admin()
    if admin_guard is not None:
        return admin_guard

    success, message, booking = complete_booking_by_id(
        booking_id,
        performed_by=_get_current_user_id(),
    )
    flash(message if not success else "Vehicle marked completed", "error" if not success else "success")
    if success:
        _refresh_cache(booking_id)
    fallback = redirect(url_for("web_admin.web_admin_checkin_page", booking_id=booking_id))
    return _redirect_with_whatsapp(booking_id, get_booking_by_id(booking_id) or booking, fallback)

