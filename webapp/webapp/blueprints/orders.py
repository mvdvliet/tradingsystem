# blueprints/orders.py
from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash
import logging
from datetime import datetime
from auth_utils import check_authentication

logger = logging.getLogger('webapp logger')

orders_bp = Blueprint('orders', __name__)

@orders_bp.route("/")
@check_authentication()
def orders():
    try:
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        # Get orders
        orders = ibkr_client.get_orders()
        
        if not orders:
            logger.warning("No orders found")
            return render_template("orders.html", orders=[])
        
        def parse_datetime(date_string):
            # Adjust the format string to match your date string format
            return datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S')

        # Parse date strings to datetime objects
        for order in orders:
            if isinstance(order.get('lastExecutionTime_r'), str):
                try:
                    order['lastExecutionTime_r'] = parse_datetime(order['lastExecutionTime_r'])
                except ValueError:
                    # Handle date parsing errors
                    order['lastExecutionTime_r'] = datetime.now()

        # Sort orders by 'lastExecutionTime_r' in descending order
        orders_sorted = sorted(orders, key=lambda x: x.get('lastExecutionTime_r', datetime.now()), reverse=True)

        # Render template with sorted orders
        return render_template("orders.html", orders=orders_sorted)
    except Exception as e:
        logger.error(f"Error retrieving orders: {e}")
        return "Error retrieving orders.", 500

@orders_bp.route("/place", methods=['POST'])
@check_authentication()
def place_order():
    try:
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        # Validate inputs
        try:
            contract_id = int(request.form.get('contract_id'))
            price = float(request.form.get('price'))
            quantity = int(request.form.get('quantity'))
        except (ValueError, TypeError):
            flash("Invalid order parameters. Please check your inputs.", "error")
            return redirect(url_for('orders.orders'))
        
        side = request.form.get('side')
        if side not in ['BUY', 'SELL']:
            flash("Invalid order side. Must be BUY or SELL.", "error")
            return redirect(url_for('orders.orders'))
        
        if price <= 0:
            flash("Price must be greater than zero.", "error")
            return redirect(url_for('orders.orders'))
            
        if quantity <= 0:
            flash("Quantity must be greater than zero.", "error")
            return redirect(url_for('orders.orders'))
        
        # Create order details
        order_details = {
            "conid": contract_id,
            "orderType": "LMT",
            "price": price,
            "quantity": quantity,
            "side": side,
            "tif": "GTC"
        }
        
        logger.info(f"Order Details: {order_details}")
        
        # Place the order
        order_id = ibkr_client.place_order(order_details)
        
        if order_id:
            # Confirm the order
            confirmation = ibkr_client.confirm_order(order_id)
            if confirmation:
                logger.info(f"Order confirmed: {confirmation}")
                flash("Order placed successfully.", "success")
            else:
                logger.error("Order confirmation failed")
                flash("Order placed but confirmation failed.", "warning")
        else:
            logger.error("Order placement failed")
            flash("Failed to place order.", "error")
            
        return redirect(url_for('orders.orders'))
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        flash(f"Error placing order: {str(e)}", "error")
        return redirect(url_for('orders.orders'))

@orders_bp.route("/<order_id>/cancel", methods=['GET', 'POST'])
@check_authentication()
def cancel_order(order_id):
    try:
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        # Cancel the order
        success = ibkr_client.cancel_order(order_id)
        
        if success:
            logger.info(f"Order {order_id} cancelled successfully")
            flash(f"Order {order_id} cancelled successfully", "success")
        else:
            logger.error(f"Failed to cancel order {order_id}")
            flash(f"Failed to cancel order {order_id}", "error")
            
        return redirect(url_for('orders.orders'))
    except Exception as e:
        logger.error(f"Error cancelling order {order_id}: {e}")
        flash(f"Error cancelling order: {str(e)}", "error")
        return redirect(url_for('orders.orders'))
    
@orders_bp.route('/ordererror')
def order_error():
    return render_template('ordererror.html')
