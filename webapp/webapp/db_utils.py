# db_utils.py
import logging
from models import db, SessionStatus, TradingUniverse, Strategy, PNL, Trades, BacktestResult, JobExecution, Signal
from sqlalchemy import inspect
from flask import current_app

logger = logging.getLogger('webapp logger')

def init_db():
    """Initialize the database by creating all tables using SQLAlchemy ORM"""
    try:
        logger.info("Starting database initialization...")
        
        # Test database connection
        try:
            connection = db.engine.connect()
            logger.info(f"✅ Successfully connected to database at {db.engine.url}")
            connection.close()
        except Exception as e:
            logger.error(f"❌ Failed to connect to database: {e}")
            raise
        
        # Get existing tables before creation
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        logger.info(f"Existing tables before initialization: {', '.join(existing_tables) if existing_tables else 'None'}")
        
        # Create all tables
        db.create_all()
        
        # Get tables after creation to determine which ones were newly created
        new_inspector = inspect(db.engine)
        current_tables = set(new_inspector.get_table_names())
        
        # Identify newly created tables
        new_tables = current_tables - existing_tables
        if new_tables:
            logger.info(f"✅ Newly created tables: {', '.join(new_tables)}")
        else:
            logger.info("ℹ️ All tables already existed, no new tables created")
        
        # Log all available tables
        logger.info(f"Available tables: {', '.join(current_tables)}")
        
        # Add sample data to TradingUniverse if empty
        if 'trading_universe' in current_tables:
            count = TradingUniverse.query.count()
            if count == 0:
                logger.info("Trading universe is empty, adding sample symbols...")
                sample_symbols = [
                    TradingUniverse(symbol="AAPL", conid=265598),
                    TradingUniverse(symbol="MSFT", conid=272093),
                    TradingUniverse(symbol="GOOGL", conid=208813720)
                ]
                
                db.session.add_all(sample_symbols)
                db.session.commit()
                logger.info("✅ Added sample symbols to trading universe")
            else:
                logger.info(f"ℹ️ Trading universe already contains {count} symbols")
                
        # Log model counts for key tables
        log_table_counts()
                
        logger.info("✅ Database initialization completed successfully")
                
    except Exception as e:
        logger.error(f"❌ Error initializing database: {e}")
        db.session.rollback()
        raise

def log_table_counts():
    """Log the number of records in each table"""
    try:
        model_classes = [
            (TradingUniverse, "Trading Universe"),
            (Strategy, "Strategies"),
            (Signal, "Signals"),
            (PNL, "PNL Records"),
            (Trades, "Trades"),
            (BacktestResult, "Backtest Results"),
            (SessionStatus, "Session Status"),
            (JobExecution, "Job Executions")
        ]
        
        logger.info("Current database table statistics:")
        for model_class, display_name in model_classes:
            try:
                count = model_class.query.count()
                logger.info(f"  • {display_name}: {count} records")
            except Exception as e:
                logger.warning(f"  • Could not count {display_name}: {e}")
    except Exception as e:
        logger.error(f"Error logging table counts: {e}")