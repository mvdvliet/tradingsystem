# blueprints/__init__.py
from flask import Blueprint

# Import blueprints
from .dashboard import dashboard_bp
from .portfolio import portfolio_bp
from .trading import trading_bp
from .strategies import strategies_bp
from .orders import orders_bp
from .scanner import scanner_bp
from .trades import trades_bp
from .pnl import pnl_bp
from .scheduler import scheduler_bp
from .auth import auth_bp
from .contract import contract_bp
from .backtest import backtest_bp
from .signals import signals_bp

def register_blueprints(app):
    """Register all blueprints with the Flask app"""
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(portfolio_bp, url_prefix='/portfolio')
    app.register_blueprint(trading_bp, url_prefix='/trading')
    app.register_blueprint(strategies_bp, url_prefix='/strategies')
    app.register_blueprint(orders_bp, url_prefix='/orders')
    app.register_blueprint(scanner_bp, url_prefix='/scanner')
    app.register_blueprint(trades_bp, url_prefix='/trades')
    app.register_blueprint(pnl_bp, url_prefix='/pnl')
    app.register_blueprint(scheduler_bp, url_prefix='/scheduler')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(contract_bp, url_prefix='/contract')
    app.register_blueprint(backtest_bp, url_prefix='/backtest')
    app.register_blueprint(signals_bp, url_prefix='/signals')