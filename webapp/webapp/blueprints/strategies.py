# blueprints/strategies.py
from flask import Blueprint, render_template, redirect, url_for, flash, current_app
import logging
from datetime import datetime
from models import db, Strategy
from auth_utils import check_authentication

logger = logging.getLogger('webapp logger')

strategies_bp = Blueprint('strategies', __name__)

@strategies_bp.route("/")
@check_authentication()
def strategies():
    try:
        # Get active strategies
        active_strategies = Strategy.query.filter_by(status='ACTIVE').order_by(Strategy.created_at.desc()).all()
        
        # Get closed strategies
        closed_strategies = Strategy.query.filter_by(status='CLOSED').order_by(Strategy.exit_time.desc()).all()
        
        return render_template(
            "strategies.html",
            active_strategies=active_strategies,
            closed_strategies=closed_strategies
        )
    except Exception as e:
        logger.error(f"Error retrieving strategies: {e}")
        flash("Error retrieving strategies.", "error")
        return redirect(url_for('dashboard.dashboard'))

@strategies_bp.route("/<int:strategy_id>/close")
@check_authentication()
def close_strategy(strategy_id):
    try:
        strategy = Strategy.query.get_or_404(strategy_id)
        if strategy.status == 'ACTIVE':
            strategy.status = 'CLOSED'
            strategy.exit_time = datetime.utcnow()
            strategy.exit_price = strategy.current_price
            db.session.commit()
            flash(f"Strategy for {strategy.symbol} closed successfully.", "success")
        else:
            flash("Strategy is already closed.", "warning")
    except Exception as e:
        logger.error(f"Error closing strategy: {e}")
        flash("Error closing strategy.", "error")
        db.session.rollback()
    
    return redirect(url_for('strategies.strategies'))