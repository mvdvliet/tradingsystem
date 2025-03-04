# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import pytz

db = SQLAlchemy()

class SessionStatus(db.Model):
    __tablename__ = 'session'
    
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String, nullable=False)
    sso_expires = db.Column(db.Integer)
    collision = db.Column(db.Boolean)
    user_id = db.Column(db.Integer)
    hmds_error = db.Column(db.String)
    authenticated = db.Column(db.Boolean, default=False)
    competing = db.Column(db.Boolean, default=False)
    connected = db.Column(db.Boolean, default=False)
    message = db.Column(db.String)
    mac_address = db.Column(db.String)
    server_name = db.Column(db.String)
    server_version = db.Column(db.String)
    hardware_info = db.Column(db.String)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class TradingUniverse(db.Model):
    __tablename__ = 'trading_universe'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String, nullable=False)
    conid = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    trading_mode = db.Column(db.String(20), default='trading', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Strategy(db.Model):
    __tablename__ = 'strategies'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    symbol = db.Column(db.String, nullable=False)
    conid = db.Column(db.Integer, nullable=False)
    entry_price = db.Column(db.Float)
    entry_time = db.Column(db.DateTime)
    position_size = db.Column(db.Integer)
    current_price = db.Column(db.Float)
    pnl = db.Column(db.Float)
    status = db.Column(db.String)  # ACTIVE, CLOSED
    exit_price = db.Column(db.Float)
    exit_time = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PNL(db.Model):
    __tablename__ = 'pnl'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    dpl = db.Column(db.Float)
    nl = db.Column(db.Float)
    upl = db.Column(db.Float)
    el = db.Column(db.Float)
    uel = db.Column(db.Float)
    mv = db.Column(db.Float)

class Trades(db.Model):
    __tablename__ = 'trades'

    execution_id = db.Column(db.String, primary_key=True)
    symbol = db.Column(db.String)
    supports_tax_opt = db.Column(db.Boolean)
    side = db.Column(db.String)
    order_description = db.Column(db.String)
    trade_time = db.Column(db.DateTime)
    trade_time_r = db.Column(db.BigInteger)
    size = db.Column(db.Integer)
    price = db.Column(db.Float)
    exchange = db.Column(db.String)
    commission = db.Column(db.Float)
    net_amount = db.Column(db.Float)
    account = db.Column(db.String)
    account_allocation_name = db.Column(db.String)
    company_name = db.Column(db.String)
    contract_description_1 = db.Column(db.String)
    sec_type = db.Column(db.String)
    listing_exchange = db.Column(db.String)
    conid = db.Column(db.BigInteger)
    position = db.Column(db.Integer)
    clearing_id = db.Column(db.String)
    clearing_name = db.Column(db.String)
    liquidation_trade = db.Column(db.Boolean)
    is_event_trading = db.Column(db.Boolean)

class BacktestResult(db.Model):
    __tablename__ = 'backtest_result'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    conid = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String)
    period = db.Column(db.String)
    bar = db.Column(db.String)
    short_window = db.Column(db.Integer)
    long_window = db.Column(db.Integer)
    initial_investment = db.Column(db.Float)
    final_portfolio_value = db.Column(db.Float)
    final_return = db.Column(db.Float)
    final_number_trades = db.Column(db.Integer)
    total_commission = db.Column(db.Float)

class JobExecution(db.Model):
    """Model for tracking job execution history."""
    __tablename__ = 'job_executions'
    
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(100), nullable=False, index=True)
    start_time = db.Column(db.DateTime, nullable=False, index=True)
    end_time = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, index=True)  # 'success', 'failed', 'running'
    execution_time = db.Column(db.Float, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    
    def __init__(self, **kwargs):
        """Initialize with timezone-aware datetimes"""
        super(JobExecution, self).__init__(**kwargs)
        
        # Ensure start_time is timezone-aware
        if self.start_time and self.start_time.tzinfo is None:
            self.start_time = pytz.timezone('Etc/UTC').localize(self.start_time)
        
        # Ensure end_time is timezone-aware if provided
        if self.end_time and self.end_time.tzinfo is None:
            self.end_time = pytz.timezone('Etc/UTC').localize(self.end_time)
    
    def __repr__(self):
        return f"<JobExecution {self.job_id} at {self.start_time}>"
    
    @classmethod
    def get_recent_executions(cls, limit=100):
        """Get recent job executions."""
        return cls.query.order_by(cls.start_time.desc()).limit(limit).all()
    
    @classmethod
    def get_executions_by_job_id(cls, job_id, limit=100):
        """Get recent job executions for a specific job."""
        return cls.query.filter_by(job_id=job_id).order_by(cls.start_time.desc()).limit(limit).all()
    
    @classmethod
    def get_failed_executions(cls, limit=100):
        """Get recent failed job executions."""
        return cls.query.filter_by(status='failed').order_by(cls.start_time.desc()).limit(limit).all()

class Signal(db.Model):
    """Model for storing trading signals detected by strategies"""
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    conid = db.Column(db.String(20), nullable=False)
    signal_type = db.Column(db.String(10), nullable=False)  # BUY, SELL
    signal_strength = db.Column(db.Float, nullable=True)
    detection_time = db.Column(db.DateTime, default=datetime.utcnow)
    current_price = db.Column(db.Float, nullable=True)
    short_ma = db.Column(db.Float, nullable=True)
    long_ma = db.Column(db.Float, nullable=True)
    ma_diff = db.Column(db.Float, nullable=True)
    prev_ma_diff = db.Column(db.Float, nullable=True)
    acted_upon = db.Column(db.Boolean, default=False)  # Whether a strategy was created/closed based on this signal
    
    def __repr__(self):
        return f"<Signal {self.signal_type} for {self.symbol} at {self.detection_time}>"