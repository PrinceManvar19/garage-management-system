import datetime
from decimal import Decimal
import psycopg2
from psycopg2.extras import RealDictCursor
from models.db import get_db, query_dict, query_dict_one, execute_query
from utils.helpers import log_action
from services.salary_service import calculate_salary


VALID_SALARY_STATUSES = {"draft", "finalized", "paid"}


def ensure_salary_status_column():
    """Add salary_status for existing salary_records tables."""
    try:
        db = get_db()
        cursor = db.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'salary_records' AND column_name = 'salary_status'
        """)
        if not cursor.fetchone():
            cursor.execute("""
                ALTER TABLE salary_records ADD COLUMN salary_status TEXT NOT NULL DEFAULT 'finalized'
            """)
            db.commit()
        cursor.close()
    except psycopg2.Error:
        pass


def ensure_payment_columns():
    """Ensure payment_status, paid_at, and payment_method exist."""
    try:
        db = get_db()
        cursor = db.cursor()
        
        columns_to_check = ['payment_status', 'paid_at', 'payment_method']
        for col in columns_to_check:
            cursor.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'salary_records' AND column_name = %s
            """, (col,))
            if not cursor.fetchone():
                if col == 'paid_at':
                    cursor.execute(f"ALTER TABLE salary_records ADD COLUMN {col} TEXT")
                else:
                    cursor.execute(f"ALTER TABLE salary_records ADD COLUMN {col} TEXT DEFAULT 'pending'")
        
        db.commit()
        cursor.close()
    except psycopg2.Error:
        pass


def ensure_updated_at_column():
    """Ensure updated_at exists."""
    try:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'salary_records' AND column_name = 'updated_at'
        """)
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE salary_records ADD COLUMN updated_at TEXT")
            db.commit()
        cursor.close()
    except psycopg2.Error:
        pass


def ensure_advance_salary_columns():
    try:
        db = get_db()
        cursor = db.cursor()
        columns = {
            "gross_salary": "REAL DEFAULT 0",
            "pocket_money_deduction": "REAL DEFAULT 0",
            "monthly_advance_entry_count": "INTEGER DEFAULT 0",
            "previous_pending_debt": "REAL DEFAULT 0",
            "debt_recovery_deduction": "REAL DEFAULT 0",
            "remaining_debt_balance": "REAL DEFAULT 0",
            "extra_salary": "REAL DEFAULT 0",
            "final_payable_salary": "REAL DEFAULT 0",
            "net_salary": "REAL DEFAULT 0",
        }
        for column, definition in columns.items():
            cursor.execute(f"""
                ALTER TABLE salary_records
                ADD COLUMN IF NOT EXISTS {column} {definition}
            """)
        db.commit()
        cursor.close()
    except psycopg2.Error:
        pass


def _normalize_paid_fields(salary_status, payment_status):
    salary_status = (salary_status or "").strip().lower()
    payment_status = (payment_status or "").strip().lower()
    if salary_status == "paid" or payment_status == "paid":
        return "paid", "paid"
    return "finalized", "unpaid"


def mark_salary_as_paid(record_id, admin_user_id=None):
    """Mark a salary record as paid and lock it from further edits."""
    ensure_salary_status_column()
    ensure_payment_columns()
    ensure_updated_at_column()

    record = get_salary_record(record_id)
    if not record:
        return False, "Salary record not found"

    current_status = (record.get("salary_status") or "").strip().lower()
    if current_status == "paid":
        return False, "This payroll record is already marked as PAID"

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    try:
        db = get_db()
        cursor = db.cursor()
        
        # Check which columns exist
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'salary_records' AND column_name IN ('updated_at')
        """)
        has_updated_at = bool(cursor.fetchone())
        
        if has_updated_at:
            cursor.execute("""
                UPDATE salary_records 
                SET salary_status = %s, payment_status = %s, paid_at = %s, updated_at = %s
                WHERE id = %s
            """, ('paid', 'paid', now, now, record_id))
        else:
            cursor.execute("""
                UPDATE salary_records 
                SET salary_status = %s, payment_status = %s, paid_at = %s
                WHERE id = %s
            """, ('paid', 'paid', now, record_id))
        
        db.commit()
        cursor.close()
        
        log_action(
            "SALARY_RECORD_MARKED_PAID",
            f"ID {record_id} by {admin_user_id or 'unknown'}"
        )
        return True, "Salary record marked as paid and locked"
    except psycopg2.Error as e:
        return False, f"Failed to mark as paid: {str(e)}"




def _normalize_salary_status(status, default="finalized"):
    status = (status or default).strip().lower()
    return status if status in VALID_SALARY_STATUSES else default


def update_salary_payment_info(record_id, payment_method=None):
    """Save payment_method to an existing record."""
    if payment_method is None and payment_method != "":
        return

    ensure_payment_columns()
    
    try:
        db = get_db()
        cursor = db.cursor()
        
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'salary_records' AND column_name = 'payment_method'
        """)
        
        if cursor.fetchone() and payment_method is not None and str(payment_method).strip():
            cursor.execute("""
                UPDATE salary_records 
                SET payment_method = %s 
                WHERE id = %s
            """, (payment_method.strip(), record_id))
            db.commit()
        
        cursor.close()
    except psycopg2.Error:
        pass





def save_salary_record(
    worker_id,
    total_days,
    attended_days,
    bonus_val=0,
    bonus_pct=False,
    ot_val=0,
    ot_pct=False,
    comm_val=0,
    comm_pct=False,
    month=None,
    year=None,
    salary_status="finalized",
    payment_method=None,
    payment_status=None,
    debt_recovery_amount=0,
    extra_salary_amount=0,
    extra_salary_note="Extra salary advance",
):
    """
    Save salary calculation to salary_records.
    Prevents duplicate (worker_id, month, year).
    Returns (success, message, record_id).
    """
    worker_id = worker_id.strip().upper()
    ensure_salary_status_column()
    ensure_advance_salary_columns()
    if not worker_id:
        return False, "Worker ID required", None

    from models.worker_model import get_worker
    worker = get_worker(worker_id)
    if not worker:
        return False, f"Worker {worker_id} not found", None

    monthly_salary = Decimal(str(worker['monthly_salary']))

    now = datetime.datetime.now()
    month = month or f"{now.month:02d}"
    year = year or now.year
    salary_status = _normalize_salary_status(salary_status)

    if payment_status is None:
        payment_status = "pending"
    if payment_method is None:
        payment_method = None

    if str(salary_status).strip().lower() == "paid" and str(payment_status).strip().lower() != "paid":
        payment_status = "paid"

    # Check duplicate
    existing = query_dict_one(
        "SELECT id FROM salary_records WHERE worker_id = %s AND month = %s AND year = %s",
        (worker_id, month, year)
    )
    if existing:
        return False, f"Salary record for {worker_id} {month}/{year} already exists", existing['id']

    from models.advance_model import (
        apply_debt_recovery,
        get_monthly_pocket_money_count,
        get_monthly_pocket_money_total,
        get_outstanding_debt_total,
    )

    pocket_money_total = get_monthly_pocket_money_total(worker_id, month, year)
    pocket_money_count = get_monthly_pocket_money_count(worker_id, month, year)
    outstanding_before = get_outstanding_debt_total(worker_id)
    requested_recovery = Decimal(str(debt_recovery_amount or 0))
    estimated_base = (monthly_salary / Decimal(str(max(total_days, 1)))) * Decimal(str(attended_days))
    max_recovery_from_pay = max(estimated_base - pocket_money_total, Decimal("0"))
    debt_recovery = min(max(requested_recovery, Decimal("0")), outstanding_before, max_recovery_from_pay)

    try:
        calc_result = calculate_salary(
            monthly_salary=float(monthly_salary),
            total_days=total_days,
            attended_days=attended_days,
            bonus=(0, False),
            overtime=(0, False),
            commission=(0, False),
            pocket_money_deduction=float(pocket_money_total),
            debt_recovery_deduction=float(debt_recovery),
        )
    except Exception as e:
        return False, f"Calculation error: {str(e)}", None

    per_day = calc_result['per_day_salary']
    base = calc_result['base_salary']
    bonus_amt = Decimal("0")
    ot_amt = Decimal("0")
    comm_amt = Decimal("0")
    gross = calc_result['gross_salary']
    total = calc_result['total_salary']

    extra_salary = Decimal(str(extra_salary_amount or 0)).quantize(Decimal("0.01"))
    if extra_salary < 0:
        extra_salary = Decimal("0")
    final_payable_salary = total + extra_salary
    net_salary = total + extra_salary
    remaining_debt_balance = max(outstanding_before - debt_recovery, Decimal("0")) + extra_salary

    cursor = None

    try:
        ensure_payment_columns()
        ensure_updated_at_column()

        db = get_db()
        cursor = db.cursor(cursor_factory=RealDictCursor)

        # Get existing columns
        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'salary_records'
        """)
        existing_columns = {row["column_name"] for row in cursor.fetchall()}

        insert_cols = [
            "worker_id", "month", "year", "total_days", "attended_days",
            "per_day_salary", "base_salary", "bonus", "overtime", "commission",
            "gross_salary", "pocket_money_deduction", "monthly_advance_entry_count",
            "previous_pending_debt", "debt_recovery_deduction", "extra_salary",
            "remaining_debt_balance", "final_payable_salary", "net_salary", "total_salary",
            "salary_status",
        ]
        insert_vals = [
            worker_id, month, year, total_days, attended_days,
            float(per_day), float(base), float(bonus_amt), float(ot_amt), float(comm_amt),
            float(gross), float(pocket_money_total), pocket_money_count,
            float(outstanding_before), float(debt_recovery), float(extra_salary),
            float(remaining_debt_balance), float(final_payable_salary), float(net_salary), float(total),
            salary_status,
        ]

        if "payment_status" in existing_columns:
            insert_cols.append("payment_status")
            insert_vals.append(payment_status)

        if "payment_method" in existing_columns:
            insert_cols.append("payment_method")
            insert_vals.append(payment_method)

        if payment_status and str(payment_status).strip().lower() == "paid" and "paid_at" in existing_columns:
            insert_cols.append("paid_at")
            insert_vals.append(datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z")

        placeholders = ", ".join(["%s"] * len(insert_vals))
        cols_sql = ", ".join(insert_cols)

        cursor.execute(f"""
            INSERT INTO salary_records ({cols_sql}) VALUES ({placeholders})
            RETURNING id
        """, tuple(insert_vals))
        
        inserted_record = cursor.fetchone()
        record_id = inserted_record["id"] if inserted_record else None
        db.commit()

        if debt_recovery > 0 and record_id:
            ok, recovered = apply_debt_recovery(
                worker_id,
                debt_recovery,
                f"{year}-{int(month):02d}-01",
                salary_record_id=record_id,
                note=f"Recovered from salary {month}/{year}",
            )
            if ok:
                remaining_after = get_outstanding_debt_total(worker_id)
                cursor = db.cursor()
                cursor.execute("""
                    UPDATE salary_records
                    SET debt_recovery_deduction = %s,
                        remaining_debt_balance = %s
                    WHERE id = %s
                """, (float(recovered), float(remaining_after), record_id))
                db.commit()
                cursor.close()

        # If admin gave extra salary, log it as a new worker debt automatically
        if extra_salary > 0 and record_id:
            from models.advance_model import add_worker_debt
            debt_date = datetime.date.today().isoformat()
            added, debt_id = add_worker_debt(
                worker_id=worker_id,
                debt_amount=float(extra_salary),
                debt_date=debt_date,
                reason=extra_salary_note or "Extra salary advance",
            )
            if added:
                updated_total_debt = get_outstanding_debt_total(worker_id)
                cursor = db.cursor()
                cursor.execute("""
                    UPDATE salary_records
                    SET remaining_debt_balance = %s
                    WHERE id = %s
                """, (float(updated_total_debt), record_id))
                db.commit()
                cursor.close()

        log_action("SALARY_RECORD_SAVED", f"{worker_id} {month}/{year} total={total:.2f}")
        return True, "Salary record saved successfully", record_id
    except psycopg2.Error as e:
        get_db().rollback()
        log_action("SALARY_RECORD_SAVE_ERROR", str(e))
        return False, f"Save failed: {str(e)}", None
    finally:
        if cursor is not None:
            cursor.close()



def get_salary_records(worker_id=None, month=None, year=None):
    """Get salary records (filter optional) with worker details JOINed."""
    ensure_salary_status_column()
    query = """
        SELECT sr.*, w.name as worker_name, w.phone as worker_phone, w.monthly_salary as worker_monthly_salary
        FROM salary_records sr
        JOIN workers w ON sr.worker_id = w.id
    """
    params = []
    where = []

    if worker_id:
        where.append("sr.worker_id = %s")
        params.append(worker_id)
    if month:
        where.append("sr.month = %s")
        params.append(month)
    if year:
        where.append("sr.year = %s")
        params.append(year)

    if where:
        query += " WHERE " + " AND ".join(where)

    query += " ORDER BY sr.year DESC, sr.month DESC"

    rows = query_dict(query, params)
    return rows


def get_salary_record(record_id):
    """Get single salary record with worker details."""
    ensure_salary_status_column()
    row = query_dict_one("""
        SELECT sr.*, w.name as worker_name, w.phone as worker_phone, w.monthly_salary as worker_monthly_salary
        FROM salary_records sr
        JOIN workers w ON sr.worker_id = w.id
        WHERE sr.id = %s
    """, (record_id,))
    return row


def update_salary_record(record_id, total_days=None, attended_days=None, bonus_val=None, bonus_pct=None, ot_val=None, ot_pct=None, comm_val=None, comm_pct=None, salary_status=None, debt_recovery_amount=None):
    """
    Update salary record fields. Recalculates all salary values.
    Returns (success, message).
    """
    record = get_salary_record(record_id)
    if not record:
        return False, "Salary record not found"

    current_status = (record.get('salary_status') or '').strip().lower()
    if current_status == 'paid':
        return False, "This payroll record has been marked as PAID and is locked from further editing."

    worker_id = record['worker_id']
    worker_monthly = record.get('worker_monthly_salary') or 0

    total_days = record['total_days'] if total_days is None else total_days
    attended_days = record['attended_days'] if attended_days is None else attended_days

    bonus_val = record.get('bonus') if bonus_val is None else bonus_val
    bonus_pct = record.get('bonus_is_percent') if bonus_pct is None else bonus_pct

    ot_val = record.get('overtime') if ot_val is None else ot_val
    ot_pct = record.get('overtime_is_percent') if ot_pct is None else ot_pct

    comm_val = record.get('commission') if comm_val is None else comm_val
    comm_pct = record.get('commission_is_percent') if comm_pct is None else comm_pct

    salary_status = _normalize_salary_status(salary_status, record.get("salary_status") or "finalized")

    try:
        calc_result = calculate_salary(
            monthly_salary=float(worker_monthly),
            total_days=total_days,
            attended_days=attended_days,
            bonus=(bonus_val, bonus_pct),
            overtime=(ot_val, ot_pct),
            commission=(comm_val, comm_pct)
        )
    except Exception as e:
        return False, f"Recalculation error: {str(e)}"

    per_day = calc_result['per_day_salary']
    base = calc_result['base_salary']
    bonus_amt = calc_result['bonus_amount']
    ot_amt = calc_result['overtime_amount']
    comm_amt = calc_result['commission_amount']
    total = calc_result['total_salary']

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    try:
        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'salary_records' AND column_name = 'updated_at'
        """)
        has_updated_at = bool(cursor.fetchone())

        if has_updated_at:
            cursor.execute("""
                UPDATE salary_records
                SET total_days = %s, attended_days = %s, per_day_salary = %s,
                    base_salary = %s, bonus = %s, overtime = %s, commission = %s,
                    total_salary = %s, salary_status = %s, updated_at = %s
                WHERE id = %s
            """, (total_days, attended_days, float(per_day), float(base),
                  float(bonus_amt), float(ot_amt), float(comm_amt), float(total),
                  salary_status, now, record_id))
        else:
            cursor.execute("""
                UPDATE salary_records
                SET total_days = %s, attended_days = %s, per_day_salary = %s,
                    base_salary = %s, bonus = %s, overtime = %s, commission = %s,
                    total_salary = %s, salary_status = %s
                WHERE id = %s
            """, (total_days, attended_days, float(per_day), float(base),
                  float(bonus_amt), float(ot_amt), float(comm_amt), float(total),
                  salary_status, record_id))

        db.commit()
        cursor.close()
        log_action("SALARY_RECORD_UPDATED", f"ID {record_id} total={total:.2f}")
        return True, "Salary record updated successfully"
    except psycopg2.Error as e:
        log_action("SALARY_RECORD_UPDATE_ERROR", str(e))
        return False, f"Update failed: {str(e)}"


def delete_salary_record(record_id):
    """Delete a salary record."""
    try:
        execute_query("DELETE FROM salary_records WHERE id = %s", (record_id,))
        log_action("SALARY_RECORD_DELETED", f"ID {record_id}")
        return True, "Salary record deleted"
    except psycopg2.Error as e:
        log_action("SALARY_RECORD_DELETE_ERROR", str(e))
        return False, f"Delete failed: {str(e)}"


def update_salary_record(record_id, total_days=None, attended_days=None, bonus_val=None, bonus_pct=None, ot_val=None, ot_pct=None, comm_val=None, comm_pct=None, debt_recovery_amount=None, extra_salary_amount=None, extra_salary_note="Extra salary advance", salary_status=None):
    """
    Update salary record fields. Recalculates all salary values.
    Returns (success, message).

    Backend security: if the record is already PAID, reject updates.
    """
    # Get current record
    record = get_salary_record(record_id)
    if not record:
        return False, "Salary record not found"

    # Backend security: reject ANY updates if paid.
    current_status = (record.get('salary_status') or '').strip().lower()
    if current_status == 'paid':
        return False, "This payroll record has been marked as PAID and is locked from further editing."


    worker_id = record['worker_id']
    worker_monthly = record.get('worker_monthly_salary') or 0

    # Use current values as defaults (important: do NOT reset to 0 when fields are omitted)
    total_days = record['total_days'] if total_days is None else total_days
    attended_days = record['attended_days'] if attended_days is None else attended_days

    bonus_val = record.get('bonus') if bonus_val is None else bonus_val
    bonus_pct = False if bonus_pct is None else bonus_pct
    ot_val = record.get('overtime') if ot_val is None else ot_val
    ot_pct = False if ot_pct is None else ot_pct
    comm_val = record.get('commission') if comm_val is None else comm_val
    comm_pct = False if comm_pct is None else comm_pct

    monthly_advance = Decimal(str(record.get("pocket_money_deduction") or 0))
    previous_pending_debt = Decimal(str(
        record.get("previous_pending_debt")
        if record.get("previous_pending_debt") not in (None, "")
        else Decimal(str(record.get("remaining_debt_balance") or 0)) + Decimal(str(record.get("debt_recovery_deduction") or 0))
    ))
    inferred_previous_debt = Decimal(str(record.get("remaining_debt_balance") or 0)) + Decimal(str(record.get("debt_recovery_deduction") or 0))
    if previous_pending_debt == 0 and inferred_previous_debt > 0:
        previous_pending_debt = inferred_previous_debt
    requested_recovery = Decimal(str(
        record.get("debt_recovery_deduction") if debt_recovery_amount is None else debt_recovery_amount
    ))
    debt_recovery = min(max(requested_recovery, Decimal("0")), max(previous_pending_debt, Decimal("0")))

    previous_extra_salary = Decimal(str(record.get("extra_salary") or 0))
    extra_salary = Decimal(str(previous_extra_salary if extra_salary_amount is None else extra_salary_amount or 0))
    if extra_salary < 0:
        extra_salary = Decimal("0")

    salary_status = _normalize_salary_status(salary_status, record.get("salary_status") or "finalized")


    # Recalculate
    try:
        calc_result = calculate_salary(
            monthly_salary=float(worker_monthly),
            total_days=total_days,
            attended_days=attended_days,
            bonus=(bonus_val, bonus_pct),
            overtime=(ot_val, ot_pct),
            commission=(comm_val, comm_pct),
            pocket_money_deduction=monthly_advance,
            debt_recovery_deduction=debt_recovery,
        )
    except Exception as e:
        return False, f"Calculation error: {str(e)}"

    per_day = calc_result['per_day_salary']
    base = calc_result['base_salary']
    bonus_amt = calc_result['bonus_amount']
    ot_amt = calc_result['overtime_amount']
    comm_amt = calc_result['commission_amount']
    gross = calc_result.get('gross_salary', base)
    total = calc_result['total_salary']

    # Persist payable-aligned fields too (required for correct PDF/render).
    final_payable_salary = total + extra_salary
    net_payable = total + extra_salary
    net_salary = total + extra_salary
    remaining_debt_balance = max(previous_pending_debt - debt_recovery, Decimal("0")) + extra_salary

    # Check which columns exist (avoid breaking old DBs).
    columns = {
        row["name"]
        for row in __import__("models.db", fromlist=["query_dict"]).query_dict("SELECT column_name as name FROM information_schema.columns WHERE table_name = 'salary_records'")
    }

    set_parts = [
        "total_days = %s",
        "attended_days = %s",
        "per_day_salary = %s",
        "base_salary = %s",
        "bonus = %s",
        "overtime = %s",
        "commission = %s",
        "gross_salary = %s",
        "total_salary = %s",
        "salary_status = %s",
    ]
    params = [
        total_days,
        attended_days,
        float(per_day),
        float(base),
        float(bonus_amt),
        float(ot_amt),
        float(comm_amt),
        float(gross),
        float(total),
        salary_status,
    ]

    # Update only if those columns exist.
    if "final_payable_salary" in columns:
        set_parts.append("final_payable_salary = %s")
        params.append(float(final_payable_salary))
    if "extra_salary" in columns:
        set_parts.append("extra_salary = %s")
        params.append(float(extra_salary))
    if "debt_recovery_deduction" in columns:
        set_parts.append("debt_recovery_deduction = %s")
        params.append(float(debt_recovery))
    if "remaining_debt_balance" in columns:
        set_parts.append("remaining_debt_balance = %s")
        params.append(float(remaining_debt_balance))
    if "previous_pending_debt" in columns:
        set_parts.append("previous_pending_debt = %s")
        params.append(float(previous_pending_debt))
    if "net_payable" in columns:
        set_parts.append("net_payable = %s")
        params.append(float(net_payable))
    if "net_salary" in columns:
        set_parts.append("net_salary = %s")
        params.append(float(net_salary))

    # If someone submitted salary_status=paid via update form, keep paid_at/payment_status consistent.
    if salary_status == "paid":
        if "payment_status" in columns:
            set_parts.append("payment_status = 'paid'")
        if "paid_at" in columns:
            set_parts.append("paid_at = %s")
            params.append(datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z")

    try:
        sql = f"UPDATE salary_records SET {', '.join(set_parts)} WHERE id = %s"
        params.append(record_id)
        from models.db import execute_query
        execute_query(sql, tuple(params))
        get_db().commit()

        if extra_salary > previous_extra_salary:
            debt_diff = extra_salary - previous_extra_salary
            if debt_diff > 0:
                from models.advance_model import add_worker_debt, get_outstanding_debt_total
                debt_date = datetime.date.today().isoformat()
                added, debt_id = add_worker_debt(
                    worker_id=worker_id,
                    debt_amount=float(debt_diff),
                    debt_date=debt_date,
                    reason=extra_salary_note or "Extra salary advance",
                )
                if added:
                    updated_total_debt = get_outstanding_debt_total(worker_id)
                    execute_query(
                        "UPDATE salary_records SET remaining_debt_balance = %s WHERE id = %s",
                        (float(updated_total_debt), record_id)
                    )
                    get_db().commit()

        log_action("SALARY_RECORD_UPDATED", f"ID {record_id} total={total:.2f}")
        return True, "Record updated successfully"
    except Exception as e:
        get_db().rollback()
        log_action("SALARY_RECORD_UPDATE_ERROR", str(e))
        return False, f"Update failed: {str(e)}"


