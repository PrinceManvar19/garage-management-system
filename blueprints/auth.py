from flask import Blueprint, redirect, session, flash, url_for

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/admin/logout')
def logout():
    """Logout route for web admin dashboard.
    
    Clears the session and redirects to the main /login page.
    """
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


# NOTE: Password reset functionality was previously tied to a non-existent
# admin_users table and has been removed. If password reset is needed in the
# future, it should be implemented as a deliberate feature using:
# - A secure token-based reset flow (not OTP)
# - The admins table as the source of truth
# - No email-based lookups (admin IDs instead)
# This blueprint should be refactored or removed once web admin login is
# consolidated fully into the /login route in routes/auth_routes.py
