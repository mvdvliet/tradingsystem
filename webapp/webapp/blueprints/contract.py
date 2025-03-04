# blueprints/contract.py
from flask import Blueprint, render_template, request, current_app, redirect, url_for, flash
from markupsafe import Markup
import requests
import logging
import time
import pandas as pd
import plotly.graph_objs as go
from plotly.io import to_html
import numpy as np
from zoneinfo import ZoneInfo
from datetime import datetime
from auth_utils import check_authentication

logger = logging.getLogger('webapp logger')

contract_bp = Blueprint('contract', __name__)

@contract_bp.route('/<int:contract_id>/<string:period>/<string:bar>', methods=['GET', 'POST'])
@check_authentication()
def contract_details(contract_id, period, bar):
    # Handle POST request for order placement
    if request.method == 'POST':
        try:
            # Get the IBKR client from app config
            ibkr_client = current_app.config.get('IBKR_CLIENT')
            
            # Validate inputs
            try:
                price = float(request.form.get('price'))
                quantity = int(request.form.get('quantity'))
            except (ValueError, TypeError):
                flash("Invalid order parameters. Please check your inputs.", "error")
                return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
            
            side = request.form.get('side')
            if side not in ['BUY', 'SELL']:
                flash("Invalid order side. Must be BUY or SELL.", "error")
                return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
            
            if price <= 0:
                flash("Price must be greater than zero.", "error")
                return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
                
            if quantity <= 0:
                flash("Quantity must be greater than zero.", "error")
                return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
            
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
            return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
    try:
        # Validate input parameters
        valid_periods = ['1d', '1w', '1m', '3m', '6m', '1y', '2y', '3y', '5y', '10y']
        valid_bars = ['1min', '5min', '15min', '30min', '1h', '1d', '1w', '1m']
        
        if period not in valid_periods:
            logger.error(f"Invalid period: {period}")
            return f"Invalid period: {period}. Valid periods are: {', '.join(valid_periods)}", 400
            
        if bar not in valid_bars:
            logger.error(f"Invalid bar: {bar}")
            return f"Invalid bar: {bar}. Valid bars are: {', '.join(valid_bars)}", 400
        
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        # Get contract details
        contract_info = ibkr_client.get_contract_details(contract_id)
        if not contract_info:
            logger.error(f"Failed to retrieve contract details for {contract_id}")
            return "Failed to retrieve contract details.", 500
        
        # Get market data
        market_data = ibkr_client.get_market_data(contract_id)
        if not market_data:
            logger.error(f"Failed to retrieve market data for {contract_id}")
            return "Failed to retrieve market data.", 500
        
        all_na = True
        for key in ['31', '70', '71', '84', '86', '87']:  # Check important fields
            if market_data.get(key) != 'N/A':
                all_na = False
                break

        if all_na:
            logger.warning(f"All market data values are N/A for {contract_id}. This may indicate the stock is not actively traded.")

        logger.info(f"Market data keys: {market_data.keys()}")
        logger.info(f"Market data content: {market_data}")

        # Get price history
        symbol = contract_info.get('symbol', 'Unknown')
        name = contract_info.get('company_name', 'Unknown')
        
        # Get price history using the client
        stock_data = ibkr_client.get_price_history(symbol, contract_id, period, bar)
        if stock_data is None or stock_data.empty:
            logger.error(f"Failed to retrieve price history for {symbol} (conid {contract_id})")
            return "Failed to retrieve price history.", 500
        
        # Calculate indicators
        if len(stock_data) >= 21:
            # Calculate Bollinger Bands
            stock_data['Middle Band'] = stock_data['Close'].rolling(window=21).mean()
            stock_data['STD'] = stock_data['Close'].rolling(window=21).std()
            stock_data['Upper Band'] = stock_data['Middle Band'] + (stock_data['STD'] * 1.95)
            stock_data['Lower Band'] = stock_data['Middle Band'] - (stock_data['STD'] * 1.95)
            
            # Calculate moving averages
            short_window = 5
            long_window = 20
            stock_data['Short_MA'] = stock_data['Close'].rolling(window=short_window).mean()
            stock_data['Long_MA'] = stock_data['Close'].rolling(window=long_window).mean()
            
            # Generate trading signals
            stock_data['Signal'] = 0
            stock_data['Signal'] = np.where(stock_data['Short_MA'] > stock_data['Long_MA'], 1, -1)
            stock_data['Signal_Change'] = stock_data['Signal'].diff()
            
            # Identify buy and sell signals
            buy_signals = stock_data[stock_data['Signal_Change'] == 2]
            sell_signals = stock_data[stock_data['Signal_Change'] == -2]
            
            # Create Plotly graph
            fig = go.Figure()
            
            # Add main traces
            fig.add_trace(go.Scatter(x=stock_data.index, y=stock_data['Close'], mode='lines', line=dict(color='black', width=2), name=f'{symbol} Close Price'))
            fig.add_trace(go.Scatter(x=stock_data.index, y=stock_data['Short_MA'], mode='lines', line=dict(color='blue', width=0.6), name=f'{short_window}-Day MA'))
            fig.add_trace(go.Scatter(x=stock_data.index, y=stock_data['Long_MA'], mode='lines', line=dict(color='orange', width=0.6), name=f'{long_window}-Day MA'))
            fig.add_trace(go.Scatter(x=stock_data.index, y=stock_data['Upper Band'], mode='lines', line=dict(color='grey', width=0.4), name='Upper Band'))
            fig.add_trace(go.Scatter(x=stock_data.index, y=stock_data['Lower Band'], mode='lines', line=dict(color='grey', width=0.4), name='Lower Band'))
            fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', marker_symbol='triangle-up', marker_color='green', marker_size=15, name='Buy Signal'))
            fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', marker_symbol='triangle-down', marker_color='red', marker_size=15, name='Sell Signal'))
            
            # Add average price line if it exists
            avg_price = market_data.get('74', 'N/A')
            if avg_price != 'N/A' and avg_price != '0' and float(avg_price) > 0:
                avg_price_float = float(avg_price)
                fig.add_trace(go.Scatter(
                    x=[stock_data.index[0], stock_data.index[-1]],
                    y=[avg_price_float, avg_price_float],
                    mode='lines',
                    line=dict(color='red', dash='dot', width=1.5),
                    name=f'Avg Price ({avg_price})'
                ))
            
            # Set layout
            fig.update_layout(
                title=f'Stock Price and MA Crossover Strategy for {name} - Period: {period} - Bar: {bar}',
                xaxis_title='Date',
                yaxis_title='Price',
                legend_title='Legend',
                xaxis=dict(
                    type='category',
                    showticklabels=False
                ),
                height=600,
                font=dict(
                    family='Arial, sans-serif',
                    size=12,
                    color='DarkSlateGray'
                )
            )
            
            # Add range slider
            fig.update_xaxes(
                rangeslider_visible=False
            )
            
            # Convert the figure to HTML
            graph_html = to_html(fig, full_html=False)
            
            return render_template(
                "contract.html", 
                contract=contract_info, 
                market_data=market_data, 
                graph_html=Markup(graph_html)
            )
        else:
            logger.error(f"Not enough data points for {symbol} (conid {contract_id})")
            return "Not enough data points to display chart.", 500
    except Exception as e:
        logger.error(f"Error in contract route: {e}")
        return f"Error retrieving contract details: {str(e)}", 500
    
@contract_bp.route('/<int:contract_id>/<string:period>/<string:bar>/close', methods=['POST'])
@check_authentication()
def close_position(contract_id, period, bar):
    try:
        # Get the IBKR client from app config
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        # Get market data to determine position size and side
        market_data = ibkr_client.get_market_data(contract_id)
        if not market_data:
            flash("Failed to retrieve market data.", "error")
            return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
        
        # Get position size
        position_size = market_data.get('76', 'N/A')
        if position_size == 'N/A' or position_size == '0':
            flash("No position to close.", "warning")
            return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
        
        # Convert position size to integer
        try:
            position_size = int(float(position_size))
        except (ValueError, TypeError):
            flash("Invalid position size.", "error")
            return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
        
        # Determine order side (opposite of position)
        side = "SELL" if position_size > 0 else "BUY"
        quantity = abs(position_size)
        
        # Get current market price for the order
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
            return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
            
        try:
            current_price = float(current_price)
        except (ValueError, TypeError):
            flash("Invalid market price.", "error")
            return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))
        
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
        return redirect(url_for('contract.contract_details', contract_id=contract_id, period=period, bar=bar))