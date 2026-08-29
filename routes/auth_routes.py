from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models.customer_model import create_customer, find_customer
from services.auth_service import (
    login_admin_by_id_and_password,
    login_customer_by_phone,
    set_user_session,
)
from utils.helpers import log_action


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # Customer login: phone number only
        phone = request.form.get("phone", "").strip()
        
        if not phone:
            flash("Phone number is required.", "error")
            return render_template("login.html")
        
        try:
            customer = login_customer_by_phone(phone)
            if customer:
                session.clear()
                set_user_session(
                    customer["id"],
                    customer["name"],
                    "customer",
                    customer.get("phone", "")
                )
                flash("Login successful!", "success")
                return redirect(url_for("customer.dashboard"))
            else:
                flash("Phone number not found. Please register first.", "error")
                return render_template("login.html")
        except Exception as error:
            log_action("CUSTOMER LOGIN ERROR", str(error))
            flash("Login failed. Please try again.", "error")
            return render_template("login.html")

    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            success, message, _customer = create_customer(
                request.form.get("name", ""),
                request.form.get("phone", ""),
                request.form.get("vehicle", ""),
            )
        except Exception as error:
            log_action("REGISTRATION ROUTE ERROR", str(error))
            flash("Registration failed. Please try again.", "error")
            return redirect(url_for("auth.register"))

        if not success:
            flash(message, "error")
            return redirect(url_for("auth.register"))
        flash("Registration successful. Please login.", "success")
        return redirect(url_for("auth.login"))
    return render_template("register.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully", "success")
    return redirect(url_for("main.home"))


@auth_bp.route("/admin", methods=["GET", "POST"])
def admin_login():
    """
    Dedicated admin login route.
    
    GET: Show admin login form
    POST: Authenticate admin with ID + password
    """
    if request.method == "POST":
        admin_id = request.form.get("admin_id", "").strip()
        password = request.form.get("password", "").strip()
        
        if not admin_id or not password:
            flash("Admin ID and password are required.", "error")
            return render_template("admin_login.html")
        
        admin = login_admin_by_id_and_password(admin_id, password)
        if admin:
            session.clear()
            set_user_session(
                admin["id"],
                admin["name"],
                "admin",
                admin.get("phone", "")
            )
            flash("Login successful!", "success")
            return redirect("/admin/dashboard")
        else:
            flash("Invalid admin ID or password.", "error")
            return render_template("admin_login.html")
    
    return render_template("admin_login.html")


@auth_bp.route("/find-id", methods=["GET", "POST"])
def find_id():
    if request.method == "POST":
        match = find_customer(
            request.form.get("name", "").strip(),
            request.form.get("phone", "").strip(),
            request.form.get("vehicle", "").strip().upper(),
        )
        if match:
            flash(f'Your Customer ID: {match["id"]}', "success")
        else:
            flash("No match found. Visit service center.", "error")
        session["show_find_id_toast"] = True
        return redirect(url_for("auth.find_id"))

    toast = session.pop("show_find_id_toast", False)
    return render_template("find_id.html", toast=toast)
