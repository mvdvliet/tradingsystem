# ./config.py

import os
import logging
import secrets
from datetime import datetime, timezone

def get_config():
    """Get the current configuration based on environment"""
    env = os.environ.get('FLASK_ENV', 'default')
    return config.get(env, config['default'])

class Config:
    """Base configuration class"""
    
    # Flask configuration
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(16)
    
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Add IBKR configurations
    IBKR_BASE_URL = os.environ.get('IBKR_BASE_URL')
    IBKR_ACCOUNT_ID = os.environ.get('IBKR_ACCOUNT_ID')
    
    # Email configuration
    EMAIL_SENDER = os.environ.get('EMAIL_SENDER')
    EMAIL_APP_PASSWORD = os.environ.get('EMAIL_APP_PASSWORD')
    EMAIL_RECEIVER = os.environ.get('EMAIL_RECEIVER')
    # Email settings
    SMTP_SERVER = os.environ.get('SMTP_SERVER')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 465))
    
    # Scheduler configuration
    SCHEDULER_API_ENABLED = True
    
    # SSL verification
    PYTHONHTTPSVERIFY = '0'
    
    # Logging configuration
    LOG_LEVEL = logging.INFO
    LOG_FORMAT = '%(asctime)s %(levelname)s:%(message)s'
    LOG_FILE = '/var/log/ibgwweb/app.log'  # Add if you want file logging

    # Trading configuration
    TRADE_PERCENTAGE = 0.50  # Default trade percentage for position sizing
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    # Trading strategy configuration
    STRATEGY_SHORT_WINDOW = int(os.environ.get('STRATEGY_SHORT_WINDOW', 5))
    STRATEGY_LONG_WINDOW = int(os.environ.get('STRATEGY_LONG_WINDOW', 20))
    STRATEGY_INITIAL_INVESTMENT = float(os.environ.get('STRATEGY_INITIAL_INVESTMENT', 10000.0))

    # PNL thresholds
    PNL_EMAIL_THRESHOLD = float(os.environ.get('PNL_EMAIL_THRESHOLD', 100.0))
    PNL_RECORD_THRESHOLD = float(os.environ.get('PNL_RECORD_THRESHOLD', 500.0))

    # Scheduler configuration
    SCHEDULER_JOBS = {
        'check_session': {
            'minutes': int(os.environ.get('SCHEDULER_CHECK_SESSION_MINUTES', 2)),
            'misfire_grace_time': 30,
            'max_instances': 1
        },
        'check_signals': {
            'minutes': int(os.environ.get('SCHEDULER_CHECK_SIGNALS_MINUTES', 5)),
            'misfire_grace_time': 30,
            'max_instances': 1
        },
        'fetch_pnl': {
            'minutes': int(os.environ.get('SCHEDULER_FETCH_PNL_MINUTES', 15)),
            'misfire_grace_time': 30,
            'max_instances': 1
        },
        'fetch_trades': {
            'hours': int(os.environ.get('SCHEDULER_FETCH_TRADES_HOURS', 24)),
            'misfire_grace_time': 30,
            'max_instances': 1
        },
        'send_pnl_email': {
            'hours': int(os.environ.get('SCHEDULER_SEND_PNL_EMAIL_HOURS', 6)),
            'misfire_grace_time': 30,
            'max_instances': 1
        }
    }

config = {
    'development': Config(),
    'production': Config(),
    'testing': Config(),
    'default': Config()
}