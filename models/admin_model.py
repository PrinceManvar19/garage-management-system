from models.db import query_dict_one


def get_admin_by_id(admin_id):
    row = query_dict_one(
        "SELECT id, name, phone FROM admins WHERE id = %s",
        (admin_id,),
    )
    return dict(row) if row else None
