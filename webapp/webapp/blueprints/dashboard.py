# blueprints/dashboard.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
import requests
import logging
from functools import wraps
from auth_utils import check_authentication

logger = logging.getLogger('webapp logger')

dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route("/")
@check_authentication()
def dashboard():
    try:
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        if not ibkr_client:
            logger.error("IBKR client not available")
            flash("IBKR client not available. Please check your configuration.", "error")
            return render_template("error.html", message="Configuration error")
        
        # Get accounts
        try:
            accounts = ibkr_client.get_accounts()
            if not accounts:
                flash("No accounts found. Please check your IBKR connection.", "warning")
                return render_template("dashboard.html", account=None, summary=None)
        except requests.RequestException as e:
            logger.error(f"API request error getting accounts: {e}")
            flash("Error connecting to IBKR API. Please try again later.", "error")
            return render_template("error.html", message="API connection error")
        
        account = accounts[0]
        account_id = account["id"]
        
        # Get account summary
        try:
            summary = ibkr_client.get_account_summary(account_id)
            if not summary:
                flash("Could not retrieve account summary.", "warning")
                summary = {}
        except requests.RequestException as e:
            logger.error(f"API request error getting account summary: {e}")
            flash("Error retrieving account summary. Using empty summary.", "warning")
            summary = {}
        
        # Log the summary keys for debugging
        logger.debug(f"Account summary keys: {summary.keys() if summary else 'None'}")
        
        return render_template("dashboard.html", account=account, summary=summary)
    except Exception as e:
        logger.error(f"Unexpected error in dashboard route: {e}")
        flash("An unexpected error occurred. Please try again later.", "error")
        return render_template("error.html", message="Unexpected error")