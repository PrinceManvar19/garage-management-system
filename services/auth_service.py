from flask import session

from models.admin_model import get_admin_by_id
from models.customer_model import get_customer_by_phone
from utils.helpers import log_action, normalize_phone
from utils.auth_helpers import verify_password


def set_user_session(user_id, name, role, phone=""):
    session["customer_id"] = user_id
    session["name"] = name
    session["phone"] = phone or ""
    session["role"] = role
    session["user"] = {
        "id": user_id,
        "name": name,
        "phone": phone or "",
        "role": role,
    }


def ensure_session_user():
    if "customer_id" not in session or "name" not in session:
        return

    role = session.get("role", "customer")
    expected = {
        "id": session["customer_id"],
        "name": session["name"],
        "phone": session.get("phone", ""),
        "role": role,
    }
    if not isinstance(session.get("user"), dict) or session["user"] != expected:
        session["user"] = expected


def login_admin_by_id_and_password(admin_id, password):
    """
    Verify admin login using admin_id + password against admins table.
    Returns admin record if credentials valid, None otherwise.
    """
    normalized_id = (admin_id or "").strip().upper()

    try:
        admin = get_admin_by_id(normalized_id)
    except Exception as error:
        log_action("ADMIN LOGIN DB ERROR", str(error))
        return None

    if not admin:
        return None

    password_hash = admin.get("password_hash")
    if not password_hash:
        log_action("ADMIN LOGIN NO PASSWORD", f"Admin {normalized_id} has no password_hash set")
        return None

    if not verify_password(password, password_hash):
        log_action("ADMIN LOGIN FAILED", f"Invalid password for admin {normalized_id}")
        return None

    return admin


def login_customer_by_phone(phone):
    """
    Verify customer login using phone number only.
    Returns customer record if found, None otherwise.
    """
    normalized_phone = normalize_phone(phone)

    if len(normalized_phone) != 10:
        return None

    try:
        customer = get_customer_by_phone(normalized_phone)
    except Exception as error:
        log_action("CUSTOMER LOGIN DB ERROR", str(error))
        return None

    return customer

