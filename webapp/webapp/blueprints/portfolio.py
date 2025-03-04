# blueprints/portfolio.py
from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash
import logging
from auth_utils import check_authentication


logger = logging.getLogger('webapp logger')

portfolio_bp = Blueprint('portfolio', __name__)

@portfolio_bp.route("/")
@check_authentication()
def portfolio():
    try:
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        account_id = current_app.config.get('IBKR_ACCOUNT_ID')
        
        # Get positions
        positions = ibkr_client.get_positions()
        
        if not positions:
            logger.warning("No positions found")
            return render_template("portfolio.html", positions=[], total_pnl=0)
        
        # Log the structure of the first position for debugging
        if positions and len(positions) > 0:
            logger.debug(f"Position data structure: {positions[0].keys()}")
        
        # Filter valid positions
        filtered_positions = []
        total_unrealized_pnl = 0
        total_market_value = 0
        total_position_value = 0
        
        for item in positions:
            try:
                # Check if the position has the required fields
                required_fields = ['conid', 'contractDesc', 'position', 'avgCost', 'mktPrice', 'mktValue', 'unrealizedPnl']
                
                if all(field in item and item[field] is not None for field in required_fields):
                    # Add a 'name' field for compatibility with the template
                    item['name'] = item.get('contractDesc', '')
                    # Add a 'ticker' field for compatibility with the template
                    item['ticker'] = item.get('contractDesc', '')
                    
                    # Calculate position value (quantity * average cost)
                    item['position_value'] = item['position'] * item['avgCost']
                    
                    filtered_positions.append(item)
                    
                    # Add to totals if values are numbers
                    if isinstance(item['unrealizedPnl'], (int, float)):
                        total_unrealized_pnl += item['unrealizedPnl']
                    
                    if isinstance(item['mktValue'], (int, float)):
                        total_market_value += item['mktValue']
                        
                    if isinstance(item['position_value'], (int, float)):
                        total_position_value += item['position_value']
                else:
                    missing_fields = [field for field in required_fields if field not in item or item[field] is None]
                    logger.warning(f"Position missing required fields {missing_fields}: {item}")
            except Exception as e:
                logger.error(f"Error processing item {item}: {e}")

        if not filtered_positions:
            logger.error("No valid positions found with required fields.")
            return "No valid positions available.", 500

        logger.info(f"Found {len(filtered_positions)} valid positions")
        logger.info(f"Total unrealized PnL: {total_unrealized_pnl}")
        
        # Calculate total percentage PnL
        total_pnl_percent = (total_unrealized_pnl / total_market_value * 100) if total_market_value > 0 else 0
        
        return render_template(
            "portfolio.html", 
            positions=filtered_positions, 
            total_unrealized_pnl=total_unrealized_pnl,
            total_market_value=total_market_value,
            total_position_value=total_position_value,
            total_pnl_percent=total_pnl_percent
        )
    except Exception as e:
        logger.error(f"Error retrieving portfolio: {e}")
        return "Error retrieving portfolio data.", 500

@portfolio_bp.route("/close_position/<int:contract_id>", methods=['POST'])
@check_authentication()
def close_position(contract_id):
    try:
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        # Get positions to find the one we want to close
        positions = ibkr_client.get_positions()
        
        if not positions:
            flash("No positions found.", "error")
            return redirect(url_for('portfolio.portfolio'))
        
        # Find the position with the matching contract ID
        position_to_close = None
        for position in positions:
            if position.get('conid') == contract_id:
                position_to_close = position
                break
        
        if not position_to_close:
            flash(f"Position with contract ID {contract_id} not found.", "error")
            return redirect(url_for('portfolio.portfolio'))
        
        # Get position size
        position_size = position_to_close.get('position')
        if position_size == 0:
            flash("No position to close.", "warning")
            return redirect(url_for('portfolio.portfolio'))
        
        # Determine order side (opposite of position)
        side = "SELL" if position_size > 0 else "BUY"
        quantity = abs(position_size)
        
        # Get current market price for the order
        market_data = ibkr_client.get_market_data(contract_id)
        if not market_data:
            flash("Failed to retrieve market data.", "error")
            return redirect(url_for('portfolio.portfolio'))
        
        current_price = None
        if side == "SELL":
            # Use bid price for selling
            current_price = market_data.get('84', 'N/A')
        else:
            # Use ask price for buying
            current_price = market_data.get('86', 'N/A')
            
        if current_price == 'N/A':
            # Fall back to last price if bid/ask not available
            current_price = market_data.get('31', 'N/A')
            
        if current_price == 'N/A':
            flash("Could not determine current market price.", "error")
            return redirect(url_for('portfolio.portfolio'))
            
        try:
            current_price = float(current_price)
        except (ValueError, TypeError):
            flash("Invalid market price.", "error")
            return redirect(url_for('portfolio.portfolio'))
        
        # Create order details
        order_details = {
            "conid": contract_id,
            "orderType": "MKT",  # Use market order to ensure execution
            "price": current_price,  # Include price for reference, though not used for market orders
            "quantity": quantity,
            "side": side,
            "tif": "DAY"  # Day order
        }
        
        logger.info(f"Close Position Order Details: {order_details}")
        
        # Place the order
        order_id = ibkr_client.place_order(order_details)
        
        if order_id:
            # Confirm the order
            confirmation = ibkr_client.confirm_order(order_id)
            if confirmation:
                logger.info(f"Close position order confirmed: {confirmation}")
                flash(f"Position close order placed successfully: {quantity} shares {side} at market price.", "success")
            else:
                logger.error("Close position order confirmation failed")
                flash("Order placed but confirmation failed.", "warning")
        else:
            logger.error("Close position order placement failed")
            flash("Failed to place order to close position.", "error")
            
        return redirect(url_for('orders.orders'))
    except Exception as e:
        logger.error(f"Error closing position: {e}")
        flash(f"Error closing position: {str(e)}", "error")
        return redirect(url_for('portfolio.portfolio'))