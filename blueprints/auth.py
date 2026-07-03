from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from datetime import datetime, timedelta, timezone
from utils.email_utils import generate_otp, hash_otp, send_otp_email
import os

auth_bp = Blueprint('auth', __name__)

# In-memory rate limit store: {email: [datetime, ...]}
RATE_LIMIT = {}

def is_rate_limited(email):
    now = datetime.now(timezone.utc)
    window = now - timedelta(minutes=15)
    timestamps = [t for t in RATE_LIMIT.get(email, []) if t > window]
    RATE_LIMIT[email] = timestamps
    return len(timestamps) >= 3

@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def login():
    if session.get('admin_logged_in'):
        return redirect(url_for('web_admin.web_admin_dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        admin_email = os.environ.get('ADMIN_EMAIL', '').lower()

        if email != admin_email or is_rate_limited(email):
            flash('If this email is registered, an OTP has been sent.', 'info')
            return render_template('admin/login.html')

        otp_code, code_hash = generate_otp()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        from db_neon import get_db_connection
        try:
            with get_db_connection() as conn:
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
        except Exception as e:
            flash('Database error. Please try again.', 'danger')
            return render_template('admin/login.html')

        RATE_LIMIT.setdefault(email, []).append(datetime.now(timezone.utc))

        try:
            send_otp_email(email, otp_code)
        except Exception as e:
            flash('Failed to send OTP email. Check Gmail config.', 'danger')
            return render_template('admin/login.html')

        session['otp_email'] = email
        flash('OTP sent! Check your inbox.', 'success')
        return redirect(url_for('auth.verify_otp'))

    return render_template('admin/login.html')


@auth_bp.route('/admin/verify-otp', methods=['GET', 'POST'])
def verify_otp():
    if 'otp_email' not in session:
        return redirect(url_for('auth.login'))

    email = session['otp_email']

    if request.method == 'POST':
        entered = request.form.get('otp', '').strip()
        entered_hash = hash_otp(entered)
        now = datetime.now(timezone.utc)

        from db_neon import get_db_connection
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, attempts FROM otp_tokens
                    WHERE email=%s AND used=FALSE AND expires_at > %s
                    ORDER BY created_at DESC LIMIT 1
                """, (email, now))
                row = cur.fetchone()

                if not row:
                    flash('OTP expired. Please request a new one.', 'danger')
                    session.pop('otp_email', None)
                    return redirect(url_for('auth.login'))

                token_id, attempts = row

                if attempts >= 5:
                    cur.execute("UPDATE otp_tokens SET used=TRUE WHERE id=%s", (token_id,))
                    conn.commit()
                    flash('Too many failed attempts. Request a new OTP.', 'danger')
                    session.pop('otp_email', None)
                    return redirect(url_for('auth.login'))

                cur.execute(
                    "SELECT id FROM otp_tokens WHERE id=%s AND code_hash=%s",
                    (token_id, entered_hash)
                )
                valid = cur.fetchone()

                if valid:
                    cur.execute("UPDATE otp_tokens SET used=TRUE WHERE id=%s", (token_id,))
                    cur.execute(
                        "DELETE FROM otp_tokens WHERE email=%s AND (used=TRUE OR expires_at < %s)",
                        (email, now)
                    )
                    conn.commit()

                    session.clear()
                    session['admin_logged_in'] = True
                    session['admin_email'] = email
                    session.permanent = True
                    return redirect(url_for('web_admin.web_admin_dashboard'))
                else:
                    cur.execute(
                        "UPDATE otp_tokens SET attempts=attempts+1 WHERE id=%s",
                        (token_id,)
                    )
                    conn.commit()
                    remaining = 4 - attempts
                    flash(f'Incorrect OTP. {remaining} attempt(s) remaining.', 'danger')

    return render_template('admin/verify_otp.html', email=email)


@auth_bp.route('/admin/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
