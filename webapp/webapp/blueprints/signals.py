# blueprints/signals.py
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app, jsonify
from models import db, Signal, Strategy, TradingUniverse
from datetime import datetime, timedelta
import pandas as pd
import logging

logger = logging.getLogger('webapp logger')

signals_bp = Blueprint('signals', __name__, url_prefix='/signals')

@signals_bp.route('/')
def signals_dashboard():
    """Display the signals dashboard"""
    # Get signals from the last 7 days by default
    days = request.args.get('days', 7, type=int)
    signal_type = request.args.get('type', 'all')
    
    # Base query
    query = Signal.query
    
    # Apply date filter
    if days > 0:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        query = query.filter(Signal.detection_time >= cutoff_date)
    
    # Apply signal type filter
    if signal_type != 'all':
        query = query.filter(Signal.signal_type == signal_type.upper())
    
    # Get signals ordered by detection time (newest first)
    signals = query.order_by(Signal.detection_time.desc()).all()
    
    # Get universe symbols for mode display
    universe = TradingUniverse.query.all()
    universe_dict = {symbol.symbol: symbol for symbol in universe}
    
    # Get signal statistics
    stats = {
        'total': len(signals),
        'buy': sum(1 for s in signals if s.signal_type == 'BUY'),
        'sell': sum(1 for s in signals if s.signal_type == 'SELL'),
        'acted_upon': sum(1 for s in signals if s.acted_upon),
        'avg_strength': sum(s.signal_strength for s in signals) / len(signals) if signals else 0
    }
    
    # Get signals by symbol
    signals_by_symbol = {}
    for signal in signals:
        if signal.symbol not in signals_by_symbol:
            signals_by_symbol[signal.symbol] = {
                'total': 0,
                'buy': 0,
                'sell': 0,
                'acted_upon': 0
            }
        
        signals_by_symbol[signal.symbol]['total'] += 1
        signals_by_symbol[signal.symbol]['buy'] += 1 if signal.signal_type == 'BUY' else 0
        signals_by_symbol[signal.symbol]['sell'] += 1 if signal.signal_type == 'SELL' else 0
        signals_by_symbol[signal.symbol]['acted_upon'] += 1 if signal.acted_upon else 0
    
    return render_template(
        'signals.html',
        signals=signals,
        stats=stats,
        signals_by_symbol=signals_by_symbol,
        days=days,
        signal_type=signal_type,
        universe_dict=universe_dict
    )

@signals_bp.route('/detail/<int:signal_id>')
def signal_detail(signal_id):
    """Display detailed information about a specific signal"""
    signal = Signal.query.get_or_404(signal_id)
    
    # Get the strategy that was created/closed based on this signal (if any)
    related_strategy = None
    if signal.acted_upon:
        if signal.signal_type == 'BUY':
            # For BUY signals, look for strategies created around the same time
            related_strategy = Strategy.query.filter_by(
                symbol=signal.symbol,
                conid=signal.conid
            ).filter(
                Strategy.entry_time >= signal.detection_time,
                Strategy.entry_time <= signal.detection_time + timedelta(minutes=5)
            ).first()
        elif signal.signal_type == 'SELL':
            # For SELL signals, look for strategies closed around the same time
            related_strategy = Strategy.query.filter_by(
                symbol=signal.symbol,
                conid=signal.conid,
                status='CLOSED'
            ).filter(
                Strategy.exit_time >= signal.detection_time,
                Strategy.exit_time <= signal.detection_time + timedelta(minutes=5)
            ).first()
    
    # Get price history around the signal time
    price_history = None
    ibkr_client = current_app.config.get('IBKR_CLIENT')
    if ibkr_client:
        try:
            # Get price history for 5 days before and after the signal
            start_date = signal.detection_time - timedelta(days=5)
            end_date = signal.detection_time + timedelta(days=5)
            
            price_history = ibkr_client.get_price_history(
                signal.symbol, 
                signal.conid,
                period='1d',
                bar='1h',
                start_date=start_date.strftime('%Y%m%d-%H:%M:%S'),
                end_date=end_date.strftime('%Y%m%d-%H:%M:%S')
            )
            
            # Convert to list of dictionaries for easier use in templates
            if price_history is not None and not price_history.empty:
                price_history = price_history.reset_index().to_dict('records')
        except Exception as e:
            logger.error(f"Error fetching price history for signal {signal_id}: {e}")
    
    # Get other signals for the same symbol
    related_signals = Signal.query.filter_by(
        symbol=signal.symbol
    ).filter(
        Signal.id != signal.id
    ).order_by(
        Signal.detection_time.desc()
    ).limit(5).all()
    
    # Calculate signal metrics
    signal_metrics = {
        'ma_crossover_strength': abs(signal.ma_diff - signal.prev_ma_diff),
        'price_to_short_ma_ratio': (signal.current_price / signal.short_ma) if signal.short_ma else None,
        'price_to_long_ma_ratio': (signal.current_price / signal.long_ma) if signal.long_ma else None,
        'ma_ratio': (signal.short_ma / signal.long_ma) if signal.short_ma and signal.long_ma else None
    }
    
    # Format the detection time in a readable format
    detection_time_formatted = signal.detection_time.strftime('%Y-%m-%d %H:%M:%S UTC')
    
    return render_template(
        'signal_details.html',  # Changed from signals/detail.html
        signal=signal,
        related_strategy=related_strategy,
        price_history=price_history,
        related_signals=related_signals,
        signal_metrics=signal_metrics,
        detection_time_formatted=detection_time_formatted
    )