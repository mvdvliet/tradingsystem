# scheduler_config.py
import logging
import time
from datetime import datetime
import pytz
from models import db, SessionStatus, PNL, Trades
import json

logger = logging.getLogger('webapp logger')

def check_session_job():
    """Job to check IBKR session status and store in database"""
    from flask import current_app
    
    logger.info("Running session check job")
    ibkr_client = current_app.config.get('IBKR_CLIENT')
    email_service = current_app.config.get('EMAIL_SERVICE')
    
    if not ibkr_client:
        logger.error("IBKR client not available")
        return False
    
    # Get session status
    session_data = ibkr_client.get_session_status()
    if not session_data:
        logger.error("Failed to get session status")
        return False
    
    # Extract authentication status
    iserver_data = session_data.get('iserver', {})
    auth_status = iserver_data.get('authStatus', {})
    
    # Create session status record
    session_status = SessionStatus(
        session_id=auth_status.get('session', ''),
        sso_expires=auth_status.get('ssoExpires', 0),
        collision=auth_status.get('collision', False),
        user_id=auth_status.get('userId', 0),
        hmds_error=auth_status.get('hmdsError', ''),
        authenticated=auth_status.get('authenticated', False),
        competing=auth_status.get('competing', False),
        connected=auth_status.get('connected', False),
        message=auth_status.get('message', ''),
        mac_address=auth_status.get('MAC', ''),
        server_name=auth_status.get('serverName', ''),
        server_version=auth_status.get('serverVersion', ''),
        hardware_info=auth_status.get('hardwareInfo', '')
    )
    
    try:
        db.session.add(session_status)
        db.session.commit()
        logger.info(f"Saved session status: authenticated={session_status.authenticated}")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error saving session status: {e}")
        return False
    
    # Check if authentication status is false and try to reauthenticate
    if not session_status.authenticated and email_service:
        # Send the alert email
        try:
            email_service.send_auth_alert()
            logger.warning(f"Authentication status: {session_status.authenticated}")
        except Exception as e:
            logger.error(f"Error sending authentication alert: {e}")
        
        # Try to reauthenticate
        try:
            reauth_data = ibkr_client.reauthenticate()
            if reauth_data:
                logger.warning(f"Reauthentication request: {reauth_data}")
            else:
                logger.error("Reauthentication failed")
                return False
        except Exception as reauth_error:
            logger.error(f"Reauthentication failed: {reauth_error}")
            return False
    
    return True

def check_signals_job():
    """Job to check for trading signals"""
    from flask import current_app
    
    logger.info("Checking for trading signals")
    strategy_manager = current_app.config.get('STRATEGY_MANAGER')
    if not strategy_manager:
        logger.error("Strategy manager not available")
        return False
    
    try:
        strategy_manager.check_signals()
        logger.info("Trading signals check completed")
        return True
    except Exception as e:
        logger.error(f"Error checking trading signals: {e}")
        return False

def fetch_pnl_job():
    """Job to fetch and store PNL data"""
    from flask import current_app
    
    # Add this at the beginning of the function
    if not current_app.config.get('IBKR_ACCOUNT_ID'):
        logger.error("IBKR account ID not configured")
        return False

    start_time = time.time()
    logger.info("PNL fetching job started")
    
    try:
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        if not ibkr_client:
            logger.error("IBKR client not available")
            return False
        
        # Get threshold from config
        MIN_PNL_THRESHOLD = current_app.config.get('PNL_RECORD_THRESHOLD', 500)
        logger.info(f"PNL record threshold: {MIN_PNL_THRESHOLD}")
        
        # Get PNL data
        logger.info("Fetching PNL data from IBKR")
        pnl_data = ibkr_client.get_pnl()
        logger.info(f"PNL data received: {pnl_data}")
        
        if not pnl_data:
            logger.error("Failed to get PNL data")
            return False
        
        # Extract metrics
        logger.info("Extracting PNL metrics")
        metrics = ibkr_client.extract_pnl_metrics(pnl_data)
        logger.info(f"Extracted metrics: {metrics}")
        
        if not metrics:
            logger.error("Failed to extract PNL metrics")
            return False
        
        # Apply threshold check
        daily_pnl = metrics['dpl']
        logger.info(f"Daily P&L: {daily_pnl}, threshold: {MIN_PNL_THRESHOLD}")
        
        if abs(daily_pnl) < MIN_PNL_THRESHOLD:
            logger.info(f"Skipping PNL record creation - DPL {daily_pnl:.2f} below threshold {MIN_PNL_THRESHOLD:.2f}")
            return True
        
        # Create PNL record
        timestamp = datetime.now(pytz.timezone('Etc/UTC'))
        pnl_record = PNL(
            timestamp=timestamp,
            dpl=metrics['dpl'],
            nl=metrics['nl'],
            upl=metrics['upl'],
            el=metrics.get('el', 0),
            uel=metrics['uel'],
            mv=metrics['mv']
        )
        
        try:
            logger.info(f"Saving PNL record: {pnl_record.__dict__}")
            db.session.add(pnl_record)
            db.session.commit()
            logger.info(f"Saved PNL record: dpl={pnl_record.dpl}, nl={pnl_record.nl}")
            return True
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error saving PNL record: {e}")
            return False
    except Exception as e:
        logger.error(f"An unexpected error occurred in fetch_pnl_job: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False
    finally:
        elapsed_time = time.time() - start_time
        logger.info(f"PNL fetching job finished in {elapsed_time:.2f} seconds")

def fetch_trades_job():
    """Job to fetch and store trades data"""
    from flask import current_app
    
    start_time = time.time()
    logger.info("Trades fetching job started")
    
    try:
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        if not ibkr_client:
            logger.error("IBKR client not available")
            return False
        
        # Get trades data
        trades_data = ibkr_client.get_trades()
        if not trades_data:
            logger.error("Failed to get trades data")
            return False
        
        # Process each trade
        for trade in trades_data:
            # Check if trade already exists
            execution_id = trade.get('execution_id')
            if not execution_id:
                logger.warning("Trade missing execution_id, skipping")
                continue
            
            existing_trade = Trades.query.filter_by(execution_id=execution_id).first()
            if existing_trade:
                logger.debug(f"Trade {execution_id} already exists, skipping")
                continue
            
            # Create trade record
            try:
                # Process trade data
                trade_time_str = trade.get('trade_time')
                trade_time = None
                if trade_time_str:
                    try:
                        trade_time = datetime.strptime(trade_time_str, '%Y%m%d-%H:%M:%S')
                    except ValueError:
                        logger.warning(f"Invalid trade time format: {trade_time_str}")
                
                trade_time_r = int(trade.get('trade_time_r', 0))
                
                trade_record = Trades(
                    execution_id=execution_id,
                    symbol=trade.get('symbol', ''),
                    supports_tax_opt=trade.get('supports_tax_opt') == '1',
                    side=trade.get('side', ''),
                    order_description=trade.get('order_description', ''),
                    trade_time=trade_time,
                    trade_time_r=trade_time_r,
                    size=int(trade.get('size', 0)),
                    price=float(trade.get('price', 0)),
                    exchange=trade.get('exchange', ''),
                    commission=float(trade.get('commission', 0)),
                    net_amount=float(trade.get('net_amount', 0)),
                    account=trade.get('account', ''),
                    account_allocation_name=trade.get('account_allocation_name', ''),
                    company_name=trade.get('company_name', ''),
                    contract_description_1=trade.get('contract_description_1', ''),
                    sec_type=trade.get('sec_type', ''),
                    listing_exchange=trade.get('listing_exchange', ''),
                    conid=int(trade.get('conid', 0)),
                    position=int(trade.get('position', 0)),
                    clearing_id=trade.get('clearing_id', ''),
                    clearing_name=trade.get('clearing_name', ''),
                    liquidation_trade=trade.get('liquidation_trade') == '1',
                    is_event_trading=trade.get('is_event_trading') == '1'
                )
                
                db.session.add(trade_record)
                db.session.commit()
                logger.info(f"Saved trade record: {execution_id}")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error saving trade record: {e}")
        
        return True
    except Exception as e:
        logger.error(f"An unexpected error occurred in fetch_trades_job: {e}")
        return False
    finally:
        elapsed_time = time.time() - start_time
        logger.info(f"Trades fetching job finished in {elapsed_time:.2f} seconds")

def send_pnl_email_job():
    """Job to send PNL email notifications"""
    from flask import current_app
    
    logger.info("PNL email job started")
    
    try:
        email_service = current_app.config.get('EMAIL_SERVICE')
        if not email_service:
            logger.error("Email service not available")
            return False
        
        ibkr_client = current_app.config.get('IBKR_CLIENT')
        if not ibkr_client:
            logger.error("IBKR client not available")
            return False
        
        account_id = current_app.config.get('IBKR_ACCOUNT_ID')
        if not account_id:
            logger.error("IBKR account ID not configured")
            return False
        
        # Get PNL data
        pnl_data = ibkr_client.get_pnl()  # Remove account_id parameter
        if not pnl_data:
            logger.error("Failed to get PNL data for email")
            return False
        
        # Extract metrics
        metrics = ibkr_client.extract_pnl_metrics(pnl_data)
        if not metrics:
            logger.error("Failed to extract PNL metrics for email")
            return False
        
        # Check if PNL exceeds threshold
        pnl_threshold = current_app.config.get('PNL_EMAIL_THRESHOLD', 1000)
        daily_pnl = metrics['dpl']
        
        if abs(daily_pnl) < pnl_threshold:
            logger.debug(f"Skipping PNL email - DPL {daily_pnl:.2f} below threshold {pnl_threshold:.2f}")
            return True
   
          # Send email
        try:
            # Convert the PNL object to a dictionary
            pnl_data = {
                'timestamp': datetime.now(pytz.timezone('Etc/UTC')),
                'dpl': metrics['dpl'],
                'upl': metrics['upl'],
                'uel': metrics['uel'],
                'mv': metrics['mv'],
                'nl': metrics['nl']
            }
            
            # Send the PNL notification
            email_service.send_pnl_notification(pnl_data)
            logger.info(f"Sent PNL email alert for daily P&L: ${daily_pnl:,.2f}")
            return True
        except Exception as e:
            logger.error(f"Error sending PNL email: {e}")
            return False
    except Exception as e:
        logger.error(f"An unexpected error occurred in send_pnl_email_job: {e}")
        return False

def initialize_scheduler(app, scheduler):
    """Initialize the scheduler with jobs"""
    logger.info("Initializing scheduler")
    
    # Get job configuration
    jobs_config = app.config.get('SCHEDULER_JOBS', {})
    
    # First, check if we need to clear existing jobs
    # Only clear if the scheduler is not running
    if not scheduler.scheduler.running:
        logger.info("Clearing existing jobs before initialization")
        scheduler.jobs = {}
    
    # Get existing job IDs to avoid duplicates
    existing_job_ids = set()
    for job in scheduler.scheduler.get_jobs():
        existing_job_ids.add(job.id)
    
    # Add jobs based on configuration
    if 'check_session' in jobs_config and 'check_session' not in existing_job_ids:
        config = jobs_config['check_session']
        minutes = config.get('minutes', 2)
        misfire_grace_time = config.get('misfire_grace_time', 30)
        max_instances = config.get('max_instances', 1)
        
        scheduler.add_job(
            'check_session', 
            check_session_job, 
            'interval', 
            minutes=minutes,
            misfire_grace_time=misfire_grace_time,
            max_instances=max_instances
        )
        logger.info(f"Added check_session job with interval {minutes} minutes")
    
    if 'check_signals' in jobs_config and 'check_signals' not in existing_job_ids:
        config = jobs_config['check_signals']
        minutes = config.get('minutes', 5)
        misfire_grace_time = config.get('misfire_grace_time', 30)
        max_instances = config.get('max_instances', 1)
        
        scheduler.add_job(
            'check_signals', 
            check_signals_job, 
            'interval', 
            minutes=minutes,
            misfire_grace_time=misfire_grace_time,
            max_instances=max_instances
        )
        logger.info(f"Added check_signals job with interval {minutes} minutes")
    
    if 'fetch_pnl' in jobs_config and 'fetch_pnl' not in existing_job_ids:
        config = jobs_config['fetch_pnl']
        minutes = config.get('minutes', 15)
        misfire_grace_time = config.get('misfire_grace_time', 30)
        max_instances = config.get('max_instances', 1)
        
        scheduler.add_job(
            'fetch_pnl', 
            fetch_pnl_job, 
            'interval', 
            minutes=minutes,
            misfire_grace_time=misfire_grace_time,
            max_instances=max_instances
        )
        logger.info(f"Added fetch_pnl job with interval {minutes} minutes")
    
    if 'fetch_trades' in jobs_config and 'fetch_trades' not in existing_job_ids:
        config = jobs_config['fetch_trades']
        hours = config.get('hours', 24)
        misfire_grace_time = config.get('misfire_grace_time', 30)
        max_instances = config.get('max_instances', 1)
        
        scheduler.add_job(
            'fetch_trades', 
            fetch_trades_job, 
            'interval', 
            hours=hours,
            misfire_grace_time=misfire_grace_time,
            max_instances=max_instances
        )
        logger.info(f"Added fetch_trades job with interval {hours} hours")
    
    if 'send_pnl_email' in jobs_config and 'send_pnl_email' not in existing_job_ids:
        config = jobs_config['send_pnl_email']
        hours = config.get('hours', 6)
        misfire_grace_time = config.get('misfire_grace_time', 30)
        max_instances = config.get('max_instances', 1)
        
        scheduler.add_job(
            'send_pnl_email', 
            send_pnl_email_job, 
            'interval', 
            hours=hours,
            misfire_grace_time=misfire_grace_time,
            max_instances=max_instances
        )
        logger.info(f"Added send_pnl_email job with interval {hours} hours")

    # Add watchdog job if it doesn't exist
    if 'watchdog' not in existing_job_ids:
        scheduler.add_job('watchdog', watchdog_job, 'interval', minutes=5)
        logger.info("Added watchdog job with interval 5 minutes")

def watchdog_job():
    """Job to check scheduler health and restart if needed"""
    from flask import current_app
    import requests
    
    logger.info("Running scheduler watchdog job")
    
    try:
        # Check if scheduler is available
        scheduler = current_app.config.get('SCHEDULER')
        if not scheduler or not scheduler.scheduler:
            logger.error("Scheduler not available")
            return False
        
        # Check if scheduler is running
        if not scheduler.scheduler.running:
            logger.warning("Scheduler is not running, attempting restart")
            try:
                response = requests.post('http://localhost:5056/scheduler-restart')
                if response.status_code == 200:
                    logger.info("Scheduler restarted successfully by watchdog")
                    return True
                else:
                    logger.error(f"Failed to restart scheduler by watchdog: {response.text}")
                    return False
            except Exception as e:
                logger.error(f"Error calling restart endpoint: {e}")
                return False
        
        # Check if any executors are shut down
        for executor_name, executor in scheduler.scheduler._executors.items():
            if hasattr(executor, '_pool') and executor._pool._shutdown:
                logger.warning(f"Executor {executor_name} is shut down, restarting scheduler")
                
                # Call the restart endpoint
                try:
                    response = requests.post('http://localhost:5056/scheduler-restart')
                    if response.status_code == 200:
                        logger.info("Scheduler restarted successfully by watchdog")
                        return True
                    else:
                        logger.error(f"Failed to restart scheduler by watchdog: {response.text}")
                        return False
                except Exception as e:
                    logger.error(f"Error calling restart endpoint: {e}")
                    return False
        
        return True
    except Exception as e:
        logger.error(f"Error in watchdog job: {e}")
        return False