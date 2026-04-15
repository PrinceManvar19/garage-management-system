from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from models.customer_model import find_customer
from services.auth_service import login_user_by_id, set_user_session


auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = login_user_by_id(request.form.get("customer_id", ""))
        if user:
            session.clear()
            set_user_session(user["id"], user["name"], user["role"], user.get("phone", ""))
            flash(f'{user["role"].title()} login successful!', "success")
            endpoint = "admin.admin_dashboard" if user["role"] == "admin" else "customer.dashboard"
            return redirect(url_for(endpoint))

        flash("Invalid ID. Try ADMIN001, ADMIN002 or a valid customer ID", "error")

    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        customer_id = "CUST" + str(int(datetime.now().timestamp()))[-4:]
        flash(f"Account created! Your ID is {customer_id} — save it to login.")
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
