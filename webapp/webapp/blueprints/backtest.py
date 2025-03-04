# blueprints/backtest.py
from flask import Blueprint, render_template, request, current_app
from markupsafe import Markup
import logging
import pandas as pd
import plotly.graph_objs as go
from plotly.io import to_html
import numpy as np
from datetime import datetime, timezone
from models import db, BacktestResult
from auth_utils import check_authentication  # Import from auth_utils instead of dashboard

logger = logging.getLogger('webapp logger')

backtest_bp = Blueprint('backtest', __name__)

@backtest_bp.route('/<int:contract_id>/<string:period>/<string:bar>', methods=['GET', 'POST'])
@check_authentication()
def run_backtest(contract_id, period, bar):
    try:
        # Get the IBKR client from app config within the request context
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        
        if request.method == 'POST':
            # Get and validate form parameters
            try:
                short_window = int(request.form.get("short_window", 5))
                long_window = int(request.form.get("long_window", 20))
                initial_investment = float(request.form.get("initial_investment", 10000))
            except ValueError:
                flash("Invalid parameters. Please enter valid numbers.", "error")
                return redirect(url_for('backtest.run_backtest', contract_id=contract_id, period=period, bar=bar))
            
            # Validate ranges
            if short_window <= 0 or short_window > 100:
                flash("Short window must be between 1 and 100.", "error")
                return redirect(url_for('backtest.run_backtest', contract_id=contract_id, period=period, bar=bar))
                
            if long_window <= 0 or long_window > 200:
                flash("Long window must be between 1 and 200.", "error")
                return redirect(url_for('backtest.run_backtest', contract_id=contract_id, period=period, bar=bar))
                
            if initial_investment <= 0:
                flash("Initial investment must be positive.", "error")
                return redirect(url_for('backtest.run_backtest', contract_id=contract_id, period=period, bar=bar))
            
            # Validate period and bar
            valid_periods = ['1d', '1w', '1m', '3m', '6m', '1y', '2y', '3y', '5y', '10y']
            valid_bars = ['1min', '5min', '15min', '30min', '1h', '1d', '1w', '1m']
            
            period = request.form.get("period", period)
            if period not in valid_periods:
                flash(f"Invalid period. Valid periods are: {', '.join(valid_periods)}", "error")
                return redirect(url_for('backtest.run_backtest', contract_id=contract_id, period='1y', bar=bar))
                
            bar = request.form.get("bar", bar)
            if bar not in valid_bars:
                flash(f"Invalid bar. Valid bars are: {', '.join(valid_bars)}", "error")
                return redirect(url_for('backtest.run_backtest', contract_id=contract_id, period=period, bar='1d'))
        else:
            short_window = 5
            long_window = 20
            initial_investment = 10000

        logger.info("Running backtest")
        
        # Validate that short_window is less than long_window
        if short_window >= long_window:
            flash("Short window must be less than long window.", "error")
            return redirect(url_for('dashboard.dashboard'))

        # Get contract details
        contract_info = ibkr_client.get_contract_details(contract_id)
        if not contract_info:
            logger.error(f"Failed to retrieve contract details for {contract_id}")
            return "Failed to retrieve contract details.", 500
        
        symbol = contract_info.get('symbol', 'Unknown')
        name = contract_info.get('company_name', 'Unknown')
        
        # Get price history
        stock_data = ibkr_client.get_price_history(symbol, contract_id, period, bar)
        if stock_data is None or stock_data.empty:
            logger.error(f"Failed to retrieve price history for {symbol} (conid {contract_id})")
            return "Failed to retrieve price history.", 500
        
        # Calculate moving averages
        stock_data['Short_MA'] = stock_data['Close'].rolling(window=short_window).mean()
        stock_data['Long_MA'] = stock_data['Close'].rolling(window=long_window).mean()
        
        # Generate trading signals
        stock_data['Signal'] = 0
        stock_data['Signal'] = np.where(stock_data['Short_MA'] > stock_data['Long_MA'], 1, -1)
        stock_data['Signal_Change'] = stock_data['Signal'].diff()
        
        # Identify buy and sell signals
        buy_signals = stock_data[stock_data['Signal_Change'] == 2]
        sell_signals = stock_data[stock_data['Signal_Change'] == -2]
        
        # Calculate Bollinger Bands if enough data
        if len(stock_data) >= 21:
            stock_data['Middle Band'] = stock_data['Close'].rolling(window=21).mean()
            stock_data['STD'] = stock_data['Close'].rolling(window=21).std()
            stock_data['Upper Band'] = stock_data['Middle Band'] + (stock_data['STD'] * 1.95)
            stock_data['Lower Band'] = stock_data['Middle Band'] - (stock_data['STD'] * 1.95)
        
        # Create Plotly graph
        data = [
            go.Scatter(x=stock_data.index, y=stock_data['Close'], mode='lines', line=dict(color='black', width=2), name=f'{symbol} Close Price'),
            go.Scatter(x=stock_data.index, y=stock_data['Short_MA'], mode='lines', line=dict(color='blue', width=0.6), name=f'{short_window}-Day MA'),
            go.Scatter(x=stock_data.index, y=stock_data['Long_MA'], mode='lines', line=dict(color='orange', width=0.6), name=f'{long_window}-Day MA'),
        ]
        
        # Add Bollinger Bands if calculated
        if 'Upper Band' in stock_data.columns:
            data.extend([
                go.Scatter(x=stock_data.index, y=stock_data['Upper Band'], mode='lines', line=dict(color='grey', width=0.4), name='Upper Band'),
                go.Scatter(x=stock_data.index, y=stock_data['Lower Band'], mode='lines', line=dict(color='grey', width=0.4), name='Lower Band'),
            ])
        
        # Add buy and sell signals
        data.extend([
            go.Scatter(x=buy_signals.index, y=buy_signals['Close'], mode='markers', marker_symbol='triangle-up', marker_color='green', marker_size=15, name='Buy Signal'),
            go.Scatter(x=sell_signals.index, y=sell_signals['Close'], mode='markers', marker_symbol='triangle-down', marker_color='red', marker_size=15, name='Sell Signal'),
        ])

        layout = go.Layout(
            title=f'Stock Price and MA Crossover Strategy for {name} - Period: {period} - Bar: {bar}',
            xaxis_title='Date',
            yaxis_title='Price',
            legend_title='Legend',
        )

        fig = go.Figure(data=data, layout=layout)

        # Update layout
        fig.update_layout(
            xaxis=dict(
                type='category',
                showticklabels=False
            ),
            height=600,
            font=dict(
                family='Arial, sans-serif',
                size=14,
                color='DarkSlateGray'
            )
        )
        
        # Add range slider
        fig.update_xaxes(
            rangeslider_visible=False,
        )

        graph_html = to_html(fig, full_html=False)

        # Initialize trading simulation variables
        current_balance = initial_investment
        shares_held = 0
        trades_list = []
        commission_per_trade = 1.0  # $1 per trade

        # Loop through the signals to simulate trades
        for i in range(len(stock_data)):
            signal = stock_data['Signal'].iloc[i]
            price = float(stock_data['Close'].iloc[i])
            current_date = stock_data.index[i]

            if stock_data['Signal_Change'].iloc[i] == 2 and current_balance >= price:
                shares_to_buy = int(current_balance / price)
                if shares_to_buy > 0:
                    trade_cost = shares_to_buy * price
                    current_balance -= trade_cost
                    current_balance -= commission_per_trade
                    shares_held += shares_to_buy
                    
                    trades_list.append({
                        'date': current_date,
                        'action': 'BUY',
                        'shares': shares_to_buy,
                        'price': price,
                        'cost': trade_cost,
                        'commission': commission_per_trade,
                        'balance': current_balance
                    })
                    
            elif stock_data['Signal_Change'].iloc[i] == -2 and shares_held > 0:
                trade_value = shares_held * price
                current_balance += trade_value
                current_balance -= commission_per_trade
                
                trades_list.append({
                    'date': current_date,
                    'action': 'SELL',
                    'shares': shares_held,
                    'price': price,
                    'cost': trade_value,
                    'commission': commission_per_trade,
                    'balance': current_balance
                })
                
                shares_held = 0

        # Calculate final results
        final_number_trades = len(trades_list)
        total_commission = final_number_trades * commission_per_trade
        final_portfolio_value = current_balance + (shares_held * float(stock_data['Close'].iloc[-1]))
        final_return = ((final_portfolio_value - initial_investment) / initial_investment) * 100

        # Save backtest result to database only on POST request
        if request.method == 'POST':
            try:
                backtest_result = BacktestResult(
                    timestamp=datetime.now(timezone.utc),
                    conid=contract_id,
                    name=name,
                    period=period,
                    bar=bar,
                    short_window=short_window,
                    long_window=long_window,
                    initial_investment=initial_investment,
                    final_portfolio_value=final_portfolio_value,
                    final_return=final_return,
                    final_number_trades=final_number_trades,
                    total_commission=total_commission
                )
                
                db.session.add(backtest_result)
                db.session.commit()
                logger.info(f"Backtest result saved successfully for {symbol}")
            except Exception as e:
                logger.error(f"Error saving backtest result: {e}")
                db.session.rollback()

        return render_template(
            "backtest.html",
            graph_html=Markup(graph_html),
            final_portfolio_value=final_portfolio_value,
            final_cash_balance=current_balance,
            final_shares_held=shares_held,
            final_return=final_return,
            final_number_trades=final_number_trades,
            total_commission=total_commission,
            trades_list=trades_list,
            period=period,
            bar=bar,
            contract_info=contract_info
        )
    except Exception as e:
        logger.error(f"Error in backtest route: {e}")
        return f"Error running backtest: {str(e)}", 500