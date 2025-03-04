# auth_utils.py
from functools import wraps
from flask import current_app, flash, redirect, url_for, request, session
import logging

logger = logging.getLogger('webapp logger')

def check_authentication():
    """
    Decorator to check if the user is authenticated with IBKR.
    
    If authentication fails, redirects to the authentication error page.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # Use the client to check session status
                ibkr_client = current_app.config.get('IBKR_CLIENT')
                if not ibkr_client:
                    logger.error("IBKR client not initialized.")
                    flash("IBKR client not initialized.", "error")
                    # Store the original URL for redirection after authentication
                    session['next_url'] = request.url
                    return redirect(url_for('auth.authentication_error'))
                
                # Remove the timeout parameter
                data = ibkr_client.get_session_status()
                
                if not data:
                    logger.error("Failed to check authentication status.")
                    flash("Failed to check authentication status. Please log in again.", "error")
                    session['next_url'] = request.url
                    return redirect(url_for('auth.authentication_error'))
                
                # Extract authentication status
                iserver_data = data.get('iserver', {})
                auth_status = iserver_data.get('authStatus', {})
                authenticated = auth_status.get('authenticated', False)
                
                if not authenticated:
                    logger.error("Session is not authenticated.")
                    flash("Session is not authenticated. Please log in again.", "error")
                    session['next_url'] = request.url
                    return redirect(url_for('auth.authentication_error'))
                
                # If we get here, authentication was successful
                return f(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error checking authentication status: {e}")
                flash("Error checking authentication status. Please log in again.", "error")
                session['next_url'] = request.url
                return redirect(url_for('auth.authentication_error'))
        return decorated_function
    return decorator

def is_authenticated():
    """
    Check if the current session is authenticated.
    
    Returns:
        bool: True if authenticated, False otherwise
    """
    try:
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        if not ibkr_client:
            return False
        
        data = ibkr_client.get_session_status()
        if not data:
            return False
        
        iserver_data = data.get('iserver', {})
        auth_status = iserver_data.get('authStatus', {})
        return auth_status.get('authenticated', False)
    except Exception as e:
        logger.error(f"Error checking authentication status: {e}")
        return False