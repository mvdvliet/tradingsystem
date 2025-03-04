# logging_utils.py
import logging
import pytz
from datetime import datetime
import os
from config import get_config

class HongKongFormatter(logging.Formatter):
    """Custom formatter that formats timestamps in Hong Kong timezone"""
    
    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp)
        hong_kong_tz = pytz.timezone('Asia/Hong_Kong')
        return dt.astimezone(hong_kong_tz)

    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S %z')

def setup_logging(name='webapp logger', level=None):
    """
    Set up logging with appropriate handlers and formatters.
    
    Args:
        name (str): Logger name
        level (int, optional): Logging level. If None, uses the level from config.
        
    Returns:
        logging.Logger: Configured logger
    """
    config = get_config()
    
    # Create or get the logger
    logger = logging.getLogger(name)
    
    # Clear any existing handlers
    logger.handlers.clear()
    
    # Set the log level
    if level is None:
        level = config.LOG_LEVEL
    logger.setLevel(level)
    
    # Create and configure the console handler
    console_handler = logging.StreamHandler()
    console_formatter = HongKongFormatter('%(asctime)s %(levelname)s:%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Add file handler if LOG_FILE is specified in config
    if hasattr(config, 'LOG_FILE') and config.LOG_FILE:
        # Ensure the log directory exists
        log_dir = os.path.dirname(config.LOG_FILE)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        file_handler = logging.FileHandler(config.LOG_FILE)
        file_formatter = HongKongFormatter('%(asctime)s %(levelname)s:%(message)s')
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    # Prevent propagation to root logger
    logger.propagate = False
    
    return logger