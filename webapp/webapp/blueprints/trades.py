# blueprints/trades.py
from flask import Blueprint, render_template, current_app
import logging
import requests
from datetime import datetime
from auth_utils import check_authentication

logger = logging.getLogger('webapp logger')

trades_bp = Blueprint('trades', __name__)

@trades_bp.route("/")
@check_authentication()
def trades():
    try:
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        # Get trades
        trades_data = ibkr_client.get_trades()
        
        if not trades_data:
            logger.warning("No trades found")
            return render_template("trades.html", trades=[])
        
        # Process each trade in the list
        for trade in trades_data:
            trade_time_str = trade.get('trade_time')
            if trade_time_str:
                try:
                    trade['trade_time_parsed'] = datetime.strptime(trade_time_str, '%Y%m%d-%H:%M:%S')
                    trade['trade_time_formatted'] = trade['trade_time_parsed'].strftime('%Y-%m-%d %H:%M:%S')
                except ValueError:
                    logger.warning(f"Invalid trade time format: {trade_time_str}")
                    trade['trade_time_parsed'] = datetime.min
                    trade['trade_time_formatted'] = 'Unknown'

        # Sort the trades by the parsed trade_time in descending order (most recent first)
        trades_data.sort(key=lambda x: x['trade_time_parsed'], reverse=True)
        
        return render_template("trades.html", trades=trades_data)
    except Exception as e:
        logger.error(f"Error retrieving trades: {e}")
        return "Error retrieving trades.", 500