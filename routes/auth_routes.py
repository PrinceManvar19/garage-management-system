from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models.customer_model import create_customer, find_customer
from services.auth_service import login_user_by_identifier, set_user_session


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        # CHANGED: Login accepts either phone number or legacy Customer/Admin ID.
        try:
            user = login_user_by_identifier(request.form.get("identifier", ""))
            if user:
                session.clear()
                set_user_session(user["id"], user["name"], user["role"], user.get("phone", ""))
                flash("Login successful", "success")
                endpoint = "admin.admin_dashboard" if user["role"] == "admin" else "customer.dashboard"
                return redirect(url_for(endpoint))
        except Exception as error:
            print("LOGIN ROUTE ERROR:", error)
            flash("Login failed. Please try again.", "error")
            return redirect(url_for("auth.login"))

        flash("User not found. Please register.", "error")

    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        # CHANGED: Registration now saves the customer and enforces unique phone numbers.
        try:
            success, message, _customer = create_customer(
                request.form.get("name", ""),
                request.form.get("phone", ""),
                request.form.get("vehicle", ""),
            )
        except Exception as error:
            print("REGISTRATION ROUTE ERROR:", error)
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
