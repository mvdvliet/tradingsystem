# blueprints/auth.py
from flask import Blueprint, render_template, redirect, url_for, flash, session, current_app
import logging
from auth_utils import is_authenticated

logger = logging.getLogger('webapp logger')

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/auth-error')
def authentication_error():
    """
    Display authentication error page with a button to check authentication status.
    """
    return render_template('auth_error.html')

@auth_bp.route('/check-auth')
def check_auth():
    """
    Check if the user is authenticated and redirect accordingly.
    """
    if is_authenticated():
        flash("Authentication successful!", "success")
        # Redirect to the original URL if available, otherwise to dashboard
        next_url = session.get('next_url')
        if next_url:
            session.pop('next_url', None)
            return redirect(next_url)
        return redirect(url_for('dashboard.dashboard'))
    else:
        flash("Authentication failed. Please log in to IBKR.", "error")
        return redirect(url_for('auth.authentication_error'))