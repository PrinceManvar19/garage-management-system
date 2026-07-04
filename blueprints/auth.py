from flask import (Blueprint, render_template, request,
                   redirect, url_for, session, flash)
from datetime import datetime, timedelta, timezone
from utils.email_utils import generate_otp, hash_otp, send_otp_email
from utils.auth_helpers import verify_password
from db_neon import get_neon_db
import os

auth_bp = Blueprint('auth', __name__)

RATE_LIMIT = {}

def is_rate_limited(email):
    now = datetime.now(timezone.utc)
    window = now - timedelta(minutes=15)
    timestamps = [t for t in RATE_LIMIT.get(email, []) if t > window]
    RATE_LIMIT[email] = timestamps
    return len(timestamps) >= 5


# ── Normal login ─────────────────────────────────────────────

@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def login():
    if session.get('admin_logged_in'):
        return redirect(url_for('web_admin.web_admin_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        try:
            conn = get_neon_db()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash FROM admin_users WHERE email = %s",
                    (email,)
                )
                row = cur.fetchone()
        except Exception:
            flash('Database error. Please try again.', 'danger')
            return render_template('admin/login.html')

        if not row or not verify_password(password, row[0]):
            flash('Invalid email or password.', 'danger')
            return render_template('admin/login.html')

        session.clear()
        session['admin_logged_in'] = True
        session['admin_email'] = email
        session.permanent = True
        return redirect(url_for('web_admin.web_admin_dashboard'))

    return render_template('admin/login.html')


@auth_bp.route('/admin/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


# ── Forgot password — step 1: request OTP ────────────────────

@auth_bp.route('/admin/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        admin_email = os.environ.get('ADMIN_EMAIL', '').lower()

        # Always show same message (prevent email enumeration)
        if email != admin_email or is_rate_limited(email):
            flash('If this email is registered, a reset code has been sent.', 'info')
            return render_template('admin/forgot_password.html')

        otp_code, code_hash = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        conn = None
        try:
            conn = get_neon_db()
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE otp_tokens SET used=TRUE WHERE email=%s AND used=FALSE",
                    (email,)
                )
                cur.execute(
                    "INSERT INTO otp_tokens (email, code_hash, expires_at) VALUES (%s, %s, %s)",
                    (email, code_hash, expires_at)
                )
            conn.commit()
        except Exception:
            if conn is not None:
                conn.rollback()
            flash('Database error. Please try again.', 'danger')
            return render_template('admin/forgot_password.html')

        RATE_LIMIT.setdefault(email, []).append(datetime.now(timezone.utc))

        try:
            send_otp_email(email, otp_code)
        except Exception:
            flash('Failed to send email. Check Gmail config.', 'danger')
            return render_template('admin/forgot_password.html')

        session['reset_email'] = email
        flash('Reset code sent! Check your inbox.', 'success')
        return redirect(url_for('auth.verify_reset_otp'))

    return render_template('admin/forgot_password.html')


# ── Forgot password — step 2: verify OTP ─────────────────────

@auth_bp.route('/admin/verify-reset-otp', methods=['GET', 'POST'])
def verify_reset_otp():
    if 'reset_email' not in session:
        return redirect(url_for('auth.forgot_password'))

    email = session['reset_email']

    if request.method == 'POST':
        entered = request.form.get('otp', '').strip()
        entered_hash = hash_otp(entered)
        now = datetime.now(timezone.utc)

        conn = get_neon_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, attempts FROM otp_tokens
                WHERE email=%s AND used=FALSE AND expires_at > %s
                ORDER BY created_at DESC LIMIT 1
            """, (email, now))
            row = cur.fetchone()

            if not row:
                flash('Code expired or not found. Request a new one.', 'danger')
                session.pop('reset_email', None)
                return redirect(url_for('auth.forgot_password'))

            token_id, attempts = row

            if attempts >= 5:
                cur.execute("UPDATE otp_tokens SET used=TRUE WHERE id=%s", (token_id,))
                conn.commit()
                flash('Too many attempts. Request a new code.', 'danger')
                session.pop('reset_email', None)
                return redirect(url_for('auth.forgot_password'))

            cur.execute(
                "SELECT id FROM otp_tokens WHERE id=%s AND code_hash=%s",
                (token_id, entered_hash)
            )
            valid = cur.fetchone()

            if valid:
                cur.execute("UPDATE otp_tokens SET used=TRUE WHERE id=%s", (token_id,))
                conn.commit()
                session['reset_verified'] = True
                return redirect(url_for('auth.set_new_password'))
            else:
                cur.execute(
                    "UPDATE otp_tokens SET attempts=attempts+1 WHERE id=%s",
                    (token_id,)
                )
                conn.commit()
                remaining = 4 - attempts
                flash(f'Incorrect code. {remaining} attempt(s) remaining.', 'danger')

    return render_template('admin/verify_reset_otp.html', email=email)


# ── Forgot password — step 3: set new password ───────────────

@auth_bp.route('/admin/set-new-password', methods=['GET', 'POST'])
def set_new_password():
    if not session.get('reset_verified') or not session.get('reset_email'):
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm', '').strip()

        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'danger')
            return render_template('admin/set_new_password.html')
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return render_template('admin/set_new_password.html')

        from utils.auth_helpers import hash_password
        hashed = hash_password(password)
        email = session['reset_email']

        conn = None
        try:
            conn = get_neon_db()
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE admin_users
                    SET password_hash=%s, updated_at=NOW()
                    WHERE email=%s
                """, (hashed, email))
            conn.commit()
        except Exception:
            if conn is not None:
                conn.rollback()
            flash('Database error. Please try again.', 'danger')
            return render_template('admin/set_new_password.html')

        session.pop('reset_email', None)
        session.pop('reset_verified', None)
        flash('Password updated successfully. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('admin/set_new_password.html')
