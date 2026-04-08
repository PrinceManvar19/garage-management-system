from flask import session

from models.admin_model import get_admin_by_id
from models.customer_model import get_customer_by_id


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


def login_user_by_id(user_id):
    normalized_id = user_id.strip().upper()
    admin = get_admin_by_id(normalized_id)
    if admin:
        return {"id": admin["id"], "name": admin["name"], "phone": "", "role": "admin"}

    customer = get_customer_by_id(normalized_id)
    if customer:
        return {
            "id": customer["id"],
            "name": customer["name"],
            "phone": customer.get("phone", ""),
            "role": "customer",
        }

    return None
