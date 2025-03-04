# blueprints/trading.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
import requests
import logging
from models import db, TradingUniverse
from auth_utils import check_authentication

logger = logging.getLogger('webapp logger')

trading_bp = Blueprint('trading', __name__)

@trading_bp.route("/lookup")
@check_authentication()
def lookup():
    try:
        symbol = request.args.get('symbol', None)
        stocks = []

        if symbol is not None:
            # Get the IBKR client from app config
            ibkr_client = current_app.config.get('IBKR_CLIENT')
            
            # Search for symbols
            stocks = ibkr_client.search_symbols(symbol)

        return render_template("lookup.html", stocks=stocks)
    except Exception as e:
        logger.error(f"Error in lookup: {e}")
        return "Error performing lookup.", 500

@trading_bp.route("/universe", methods=['GET', 'POST'])
@check_authentication()
def trading_universe():
    try:
        if request.method == 'POST':
            symbol = request.form.get('symbol')
            conid = request.form.get('conid')
            trading_mode = request.form.get('trading_mode', 'trading')  # Get trading_mode with default 'trading'
            
            # Validate inputs
            if not symbol or not conid:
                flash("Symbol and ConID are required.", "error")
                universe = TradingUniverse.query.all()
                return render_template("universe.html", universe=universe)
            
            try:
                conid = int(conid)
            except ValueError:
                flash("ConID must be a number.", "error")
                universe = TradingUniverse.query.all()
                return render_template("universe.html", universe=universe)
            
            # Check if symbol already exists
            existing = TradingUniverse.query.filter_by(symbol=symbol).first()
            if existing:
                flash(f"Symbol {symbol} already exists in the universe.", "warning")
                universe = TradingUniverse.query.all()
                return render_template("universe.html", universe=universe)
            
            # Validate trading_mode
            if trading_mode not in ['trading', 'simulation']:
                trading_mode = 'trading'  # Default to trading if invalid value
            
            # Create new universe item with trading_mode
            universe_item = TradingUniverse(
                symbol=symbol, 
                conid=conid,
                trading_mode=trading_mode
            )
            db.session.add(universe_item)
            db.session.commit()
            
            flash(f"Added {symbol} to trading universe in {trading_mode} mode.", "success")
            
        universe = TradingUniverse.query.all()
        return render_template("universe.html", universe=universe)
    except Exception as e:
        logger.error(f"Error in trading universe: {e}")
        flash("Error managing trading universe.", "error")
        return redirect(url_for('dashboard.dashboard'))

@trading_bp.route('/universe/add', methods=['POST'])
def add_to_universe():
    """Add a symbol to the trading universe"""
    symbol = request.form.get('symbol')
    conid = request.form.get('conid')
    trading_mode = request.form.get('trading_mode', 'trading')
    
    if not symbol or not conid:
        flash('Symbol and ConID are required', 'danger')
        return redirect(url_for('trading.universe'))
    
    # Check if symbol already exists
    existing = TradingUniverse.query.filter_by(symbol=symbol).first()
    if existing:
        flash(f'Symbol {symbol} already exists in the universe', 'warning')
        return redirect(url_for('trading.universe'))
    
    # Add to universe
    new_symbol = TradingUniverse(
        symbol=symbol,
        conid=conid,
        is_active=True,
        trading_mode=trading_mode
    )
    
    db.session.add(new_symbol)
    db.session.commit()
    
    flash(f'Added {symbol} to trading universe in {trading_mode} mode', 'success')
    return redirect(url_for('trading.universe'))

@trading_bp.route("/universe/symbol/<int:symbol_id>/activate")
@check_authentication()
def activate_symbol(symbol_id):
    try:
        symbol = TradingUniverse.query.get_or_404(symbol_id)
        symbol.is_active = True
        db.session.commit()
        flash(f"Symbol {symbol.symbol} has been activated.", "success")
        return redirect(url_for('trading.trading_universe'))
    except Exception as e:
        logger.error(f"Error activating symbol: {e}")
        flash("Error activating symbol.", "error")
        return redirect(url_for('trading.trading_universe'))

@trading_bp.route("/universe/symbol/<int:symbol_id>/deactivate")
@check_authentication()
def deactivate_symbol(symbol_id):
    try:
        symbol = TradingUniverse.query.get_or_404(symbol_id)
        symbol.is_active = False
        db.session.commit()
        flash(f"Symbol {symbol.symbol} has been deactivated.", "success")
        return redirect(url_for('trading.trading_universe'))
    except Exception as e:
        logger.error(f"Error deactivating symbol: {e}")
        flash("Error deactivating symbol.", "error")
        return redirect(url_for('trading.trading_universe'))

@trading_bp.route("/universe/symbol/<int:symbol_id>/toggle-mode")
@check_authentication()
def toggle_mode(symbol_id):
    """Toggle the trading mode of a symbol in the universe"""
    try:
        symbol = TradingUniverse.query.get_or_404(symbol_id)
        
        # Toggle the mode
        if symbol.trading_mode == 'trading':
            symbol.trading_mode = 'simulation'
            message = f"Changed {symbol.symbol} to simulation mode (signals only, no orders)."
        else:
            symbol.trading_mode = 'trading'
            message = f"Changed {symbol.symbol} to trading mode (signals will execute orders)."
        
        db.session.commit()
        flash(message, "success")
        return redirect(url_for('trading.trading_universe'))
    except Exception as e:
        logger.error(f"Error toggling trading mode: {e}")
        flash("Error changing trading mode.", "error")
        return redirect(url_for('trading.trading_universe'))
    
@trading_bp.route('/universe/bulk-import', methods=['GET', 'POST'])
def bulk_import():
    """Bulk import symbols to the universe in simulation mode"""
    if request.method == 'POST':
        symbols_text = request.form.get('symbols')
        if not symbols_text:
            flash('No symbols provided', 'danger')
            return redirect(url_for('trading.bulk_import'))
        
        # Parse symbols (assuming format: SYMBOL,CONID)
        symbols = []
        for line in symbols_text.strip().split('\n'):
            parts = line.strip().split(',')
            if len(parts) >= 2:
                symbol = parts[0].strip()
                conid = parts[1].strip()
                symbols.append((symbol, conid))
        
        # Add symbols to universe
        added = 0
        skipped = 0
        for symbol, conid in symbols:
            # Check if symbol already exists
            existing = TradingUniverse.query.filter_by(symbol=symbol).first()
            if existing:
                skipped += 1
                continue
            
            # Add to universe in simulation mode
            new_symbol = TradingUniverse(
                symbol=symbol,
                conid=conid,
                is_active=True,
                trading_mode='simulation'  # Default to simulation for bulk imports
            )
            
            db.session.add(new_symbol)
            added += 1
        
        db.session.commit()
        flash(f'Added {added} symbols to universe in simulation mode. Skipped {skipped} existing symbols.', 'success')
        return redirect(url_for('trading.universe'))
    
    return render_template('bulk_import.html')