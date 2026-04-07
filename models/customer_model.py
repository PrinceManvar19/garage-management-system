from models.db import get_db


def get_customer_by_id(customer_id):
    row = get_db().execute(
        "SELECT id, name, phone, vehicle FROM customers WHERE id = ?",
        (customer_id,),
    ).fetchone()
    return dict(row) if row else None


def find_customer(name, phone, vehicle):
    row = get_db().execute(
        """
        SELECT id, name, phone, vehicle
        FROM customers
        WHERE name = ? AND phone = ? AND vehicle = ?
        """,
        (name, phone, vehicle),
    ).fetchone()
    return dict(row) if row else None


def get_customer_map():
    rows = get_db().execute("SELECT id, name, phone, vehicle FROM customers").fetchall()
    return {row["id"]: dict(row) for row in rows}
