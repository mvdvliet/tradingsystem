import logging
import requests
import os
import gc
import signal
import pytz
from flask import Flask
from models import db
from scheduler import FlaskJobScheduler
from ibkr_client import IBKRClient
from strategy_manager import StrategyManager
from email_service import EmailService
from config import get_config
from logging_utils import setup_logging
from blueprints import register_blueprints
from db_utils import init_db
from scheduler_config import initialize_scheduler
from flask import current_app, jsonify
from sqlalchemy import inspect
from werkzeug.serving import is_running_from_reloader
from apscheduler.schedulers.background import BackgroundScheduler
from concurrent.futures import ThreadPoolExecutor

# disable warnings until you install a certificate
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Get configuration
config = get_config()

# Initialize logger
logger = setup_logging()

# Initialize Flask app
app = Flask(__name__)
app.config.from_object(config)

# Use configuration values
app.secret_key = config.SECRET_KEY

# Initialize database with configuration
app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS
app.config['PNL_RECORD_THRESHOLD'] = config.PNL_RECORD_THRESHOLD
app.config['PNL_EMAIL_THRESHOLD'] = config.PNL_EMAIL_THRESHOLD
app.config['SCHEDULER_JOBS'] = config.SCHEDULER_JOBS

# Log database connection information
logger.info(f"Connecting to database: {config.SQLALCHEMY_DATABASE_URI}")
db.init_app(app)
logger.info("Database connection initialized")

with app.app_context():
    try:
        logger.info("Initializing database tables...")
        init_db()  # Initialize database tables
        logger.info("Database initialization complete")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

def create_ibkr_client():
    """Create a fresh IBKR client instance"""
    from ibkr_client import IBKRClient
    return IBKRClient(
        base_url=config.IBKR_BASE_URL,
        account_id=config.IBKR_ACCOUNT_ID,
        max_retries=config.MAX_RETRIES,
        retry_delay=config.RETRY_DELAY
    )

# Initialize the IBKR client with configuration
ibkr_client = create_ibkr_client()

# Initialize the email service with your credentials
email_service = EmailService(
    sender_email=config.EMAIL_SENDER,
    sender_password=config.EMAIL_APP_PASSWORD,
    smtp_server=config.SMTP_SERVER,
    smtp_port=config.SMTP_PORT
)

# Initialize the strategy manager
strategy_manager = StrategyManager(ibkr_client, email_service)

def cleanup_schedulers():
    """Find and shut down any existing schedulers to prevent duplicates"""
    import gc
    from apscheduler.schedulers.base import BaseScheduler
    
    logger.info("Cleaning up existing schedulers...")
    schedulers_shutdown = 0
    
    # Find all scheduler instances
    for obj in gc.get_objects():
        if isinstance(obj, BaseScheduler):
            if hasattr(obj, 'running') and obj.running:
                try:
                    logger.info(f"Shutting down existing scheduler instance: {id(obj)}")
                    obj.shutdown(wait=False)
                    schedulers_shutdown += 1
                except Exception as e:
                    logger.error(f"Error shutting down scheduler {id(obj)}: {e}")
    
    # Force garbage collection
    gc.collect()
    
    logger.info(f"Cleaned up {schedulers_shutdown} scheduler instances")
    return schedulers_shutdown

# Only create and start the scheduler if we're not in a reloader subprocess or we're in the main reloader process
if not is_running_from_reloader() or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    # Clean up any existing schedulers
    cleanup_schedulers()
    
    # Initialize the scheduler
    scheduler = FlaskJobScheduler(app)
    logger.info(f"Scheduler initialized. Running: {scheduler.scheduler.running}")
    
    # Initialize and start the scheduler
    with app.app_context():
        # Initialize the scheduler with jobs
        initialize_scheduler(app, scheduler)
        logger.info(f"Scheduler jobs initialized. Running: {scheduler.scheduler.running}")
        
        # Start the scheduler
        success = scheduler.start()
        if success:
            logger.info(f"Scheduler started successfully. Running: {scheduler.scheduler.running}")
        else:
            logger.error("Failed to start scheduler")
    
    # Make the scheduler available to the application
    app.config['SCHEDULER'] = scheduler
else:
    # In the reloader process, don't start the scheduler
    logger.info("Running in reloader process, not starting scheduler")
    app.config['SCHEDULER'] = None

# Make services available to blueprints
app.config['IBKR_CLIENT'] = ibkr_client
app.config['EMAIL_SERVICE'] = email_service
app.config['STRATEGY_MANAGER'] = strategy_manager
app.config['IBKR_BASE_URL'] = config.IBKR_BASE_URL
app.config['IBKR_ACCOUNT_ID'] = config.IBKR_ACCOUNT_ID

# Register all blueprints with the app
register_blueprints(app)

def format_datetime(value, timezone_str='UTC', fmt='%Y-%m-%d %H:%M:%S'):
    """
    Converts an epoch timestamp to a formatted datetime string in the specified timezone.
    
    :param value: The epoch timestamp (int or float).
    :param timezone_str: The timezone string, e.g., 'Asia/Hong_Kong'.
    :param fmt: The datetime format string.
    :return: A formatted datetime string in the specified timezone.
    """
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    
    try:
        # Check if value is None or not a number
        if value is None or not isinstance(value, (int, float)):
            return "Invalid timestamp"
            
        # Check if the timestamp is in milliseconds and convert to seconds
        if value > 1e12:
            value = value / 1000
        # Convert epoch time to an aware datetime in UTC
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
        # Convert to the target timezone
        dt = dt.astimezone(ZoneInfo(timezone_str))
        # Format the datetime as a string
        return dt.strftime(fmt)
    except Exception as e:
        logger.error(f"Error formatting datetime: {e}")
        return "Error formatting datetime"

# Register the filter after creating the Flask app instance
app.jinja_env.filters['format_datetime'] = format_datetime

@app.route('/health')
def health():
    """Simple health check endpoint"""
    return jsonify({
        'status': 'ok',
        'message': 'Service is running'
    }), 200

@app.route('/system-health')
def system_health():
    """Comprehensive health check endpoint"""
    health = {
        'status': 'ok',
        'components': {}
    }
    
    # Check database
    try:
        result = db.session.execute("SELECT 1").fetchone()
        health['components']['database'] = {
            'status': 'ok' if result[0] == 1 else 'error',
            'message': 'Database connection successful' if result[0] == 1 else 'Database query failed'
        }
    except Exception as e:
        health['components']['database'] = {
            'status': 'error',
            'message': f'Database connection failed: {str(e)}'
        }
        health['status'] = 'error'
    
    # Check scheduler
    scheduler = current_app.config.get('SCHEDULER')
    if scheduler:
        health['components']['scheduler'] = {
            'status': 'ok' if scheduler.scheduler.running else 'error',
            'message': 'Scheduler running' if scheduler.scheduler.running else 'Scheduler not running',
            'job_count': len(scheduler.jobs),
            'health_metrics': scheduler.health_check.get_health_status()
        }
        
        # Check executors
        executor_status = {}
        for executor_name, executor in scheduler.scheduler._executors.items():
            if hasattr(executor, '_pool'):
                executor_status[executor_name] = {
                    'shutdown': executor._pool._shutdown,
                    'threads': executor._pool._max_workers
                }
                if executor._pool._shutdown:
                    health['status'] = 'error'
                    health['components']['scheduler']['status'] = 'error'
                    health['components']['scheduler']['message'] = f'Executor {executor_name} is shut down'
        
        health['components']['scheduler']['executors'] = executor_status
    else:
        health['components']['scheduler'] = {
            'status': 'error',
            'message': 'Scheduler not initialized'
        }
        health['status'] = 'error'
    
    # Check IBKR API
    ibkr_client = current_app.config.get('IBKR_CLIENT')
    if ibkr_client:
        try:
            data = ibkr_client.get_session_status()
            if data:
                iserver_data = data.get('iserver', {})
                auth_status = iserver_data.get('authStatus', {})
                authenticated = auth_status.get('authenticated', False)
                
                health['components']['ibkr_api'] = {
                    'status': 'ok' if authenticated else 'warning',
                    'message': 'IBKR API is accessible and authenticated' if authenticated else 'IBKR API is accessible but not authenticated'
                }
            else:
                health['components']['ibkr_api'] = {
                    'status': 'error',
                    'message': 'Cannot connect to IBKR API'
                }
                health['status'] = 'error'
        except Exception as e:
            health['components']['ibkr_api'] = {
                'status': 'error',
                'message': f'Error connecting to IBKR API: {str(e)}'
            }
            health['status'] = 'error'
    else:
        health['components']['ibkr_api'] = {
            'status': 'error',
            'message': 'IBKR client not initialized'
        }
        health['status'] = 'error'
    
    return jsonify(health), 200 if health['status'] == 'ok' else 500


@app.route('/scheduler-instances')
def scheduler_instances():
    """Debug endpoint to check for multiple scheduler instances"""
    # Find all BackgroundScheduler instances
    schedulers = []
    for obj in gc.get_objects():
        if isinstance(obj, BackgroundScheduler):
            schedulers.append({
                'id': id(obj),
                'running': obj.running,
                'job_count': len(obj.get_jobs())
            })
    
    return jsonify({
        'scheduler_count': len(schedulers),
        'schedulers': schedulers
    })

@app.route('/scheduler-debug')
def scheduler_debug():
    """Debug endpoint to check scheduler status"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    # Get scheduler information
    scheduler_info = {
        'running': scheduler.scheduler.running,
        'job_count': len(scheduler.jobs),
        'job_ids': list(scheduler.jobs.keys()),
        'next_run_times': {},
        'health_metrics': scheduler.health_check.get_health_status()
    }
    
    # Get next run times from the actual APScheduler jobs
    for job_id in scheduler.jobs.keys():
        apscheduler_job = scheduler.scheduler.get_job(job_id)
        if apscheduler_job:
            scheduler_info['next_run_times'][job_id] = str(apscheduler_job.next_run_time) if apscheduler_job.next_run_time else None
        else:
            scheduler_info['next_run_times'][job_id] = None
    
    # Get APScheduler information
    apscheduler_jobs = []
    for job in scheduler.scheduler.get_jobs():
        job_info = {
            'id': job.id,
            'name': job.name if hasattr(job, 'name') else job.id
        }
        
        # Safely add next_run_time
        if hasattr(job, 'next_run_time') and job.next_run_time is not None:
            job_info['next_run_time'] = str(job.next_run_time)
        else:
            job_info['next_run_time'] = None
            
        # Safely add trigger
        if hasattr(job, 'trigger'):
            job_info['trigger'] = str(job.trigger)
        else:
            job_info['trigger'] = 'unknown'
            
        apscheduler_jobs.append(job_info)
    
    return jsonify({
        'scheduler_info': scheduler_info,
        'apscheduler_jobs': apscheduler_jobs
    })

@app.route('/scheduler-start', methods=['POST'])
def scheduler_start():
    """Endpoint to manually start the scheduler"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        if scheduler.scheduler.running:
            return jsonify({'message': 'Scheduler already running'}), 200
        
        success = scheduler.start()
        if success:
            return jsonify({'message': 'Scheduler started successfully'}), 200
        else:
            return jsonify({'error': 'Failed to start scheduler'}), 500
    except Exception as e:
        return jsonify({'error': f'Error starting scheduler: {str(e)}'}), 500

@app.route('/scheduler-restart', methods=['POST'])
def scheduler_restart():
    """Endpoint to completely restart the scheduler"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        # First shut down the scheduler
        if scheduler.scheduler.running:
            # Pause all jobs
            for job in scheduler.scheduler.get_jobs():
                job.pause()
            logger.info("All jobs paused before shutdown")
            
            # Remove all jobs
            scheduler.scheduler.remove_all_jobs()
            logger.info("All jobs removed from scheduler")
            
            # Shutdown the scheduler
            scheduler.scheduler.shutdown(wait=True)
            logger.info("Scheduler shutdown complete")
            
            # Clear all job locks
            for job_id, lock in scheduler.job_locks.items():
                if lock.locked():
                    try:
                        lock.release()
                        logger.info(f"Released lock for job {job_id}")
                    except RuntimeError:
                        # Lock might be owned by a different thread
                        pass
            scheduler.job_locks = {}
            
            # Force garbage collection
            import gc
            gc.collect()
        
        # Create fresh executors
        executors = {
            'default': {
                'type': 'threadpool',
                'max_workers': 20
            },
            'threadpool': {
                'type': 'threadpool',
                'max_workers': 20
            }
        }
        
        # Create a new scheduler with fresh executors
        job_defaults = {
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 60
        }
        
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz
        
        scheduler.scheduler = BackgroundScheduler(
            executors=executors,
            job_defaults=job_defaults,
            timezone=pytz.timezone('Etc/UTC'),
            daemon=False
        )
        
        # Store the original jobs
        original_jobs = scheduler.jobs.copy()
        
        # Clear all jobs
        scheduler.jobs = {}
        
        # Reinitialize the scheduler with jobs
        with current_app.app_context():
            from scheduler_config import initialize_scheduler
            initialize_scheduler(current_app, scheduler)
        
        # Start the scheduler
        logger.info("Starting scheduler with fresh executors...")
        scheduler.scheduler.start()
        logger.info(f"Scheduler started successfully. Running: {scheduler.scheduler.running}")
        
        return jsonify({'message': 'Scheduler restarted successfully with fresh executors'}), 200
    except Exception as e:
        logger.error(f"Error restarting scheduler: {e}")
        return jsonify({'error': f'Error restarting scheduler: {str(e)}'}), 500

@app.route('/scheduler-stop', methods=['POST'])
def scheduler_stop():
    """Endpoint to completely stop the scheduler"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        success = scheduler.shutdown()
        if success:
            return jsonify({'message': 'Scheduler stopped successfully'}), 200
        else:
            return jsonify({'error': 'Failed to stop scheduler'}), 500
    except Exception as e:
        return jsonify({'error': f'Error stopping scheduler: {str(e)}'}), 500
    
@app.route('/scheduler-reset', methods=['POST'])
def scheduler_reset():
    """Reset the scheduler with a fresh application context"""
    try:
        # Get the current scheduler
        scheduler = current_app.config.get('SCHEDULER')
        if not scheduler:
            return jsonify({'error': 'Scheduler not initialized'}), 500
        
        # Shut down the scheduler
        if scheduler.scheduler.running:
            scheduler.shutdown()
        
        # Update the app reference
        scheduler.app = current_app._get_current_object()
        
        # Start the scheduler with fresh executors
        success = scheduler.start()
        
        # Reinitialize jobs
        with current_app.app_context():
            from scheduler_config import initialize_scheduler
            initialize_scheduler(current_app, scheduler)
        
        return jsonify({
            'message': 'Scheduler reset with fresh application context',
            'success': success,
            'running': scheduler.scheduler.running
        }), 200
    except Exception as e:
        logger.error(f"Error resetting scheduler: {e}")
        return jsonify({'error': f'Error resetting scheduler: {str(e)}'}), 500
    
@app.route('/scheduler-kill', methods=['POST'])
def scheduler_kill():
    """Endpoint to forcefully kill all scheduler threads"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        # Shutdown the scheduler
        if scheduler.scheduler.running:
            scheduler.shutdown()
        
        # Force garbage collection
        import gc
        gc.collect()
        
        # Find and kill any lingering APScheduler threads
        import threading
        killed_threads = 0
        for thread in threading.enumerate():
            if 'APScheduler' in thread.name:
                logger.warning(f"Found lingering APScheduler thread: {thread.name}")
                # We can't forcefully kill threads in Python, but we can set a flag
                if hasattr(thread, '_stop'):
                    thread._stop()
                    killed_threads += 1
        
        return jsonify({
            'message': f'Scheduler killed, attempted to stop {killed_threads} lingering threads',
            'killed_threads': killed_threads
        }), 200
    except Exception as e:
        return jsonify({'error': f'Error killing scheduler: {str(e)}'}), 500

@app.route('/scheduler-status', methods=['GET'])
def scheduler_status():
    """Endpoint to check the status of all scheduler threads"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        # Get all threads
        import threading
        threads = []
        for thread in threading.enumerate():
            thread_info = {
                'name': thread.name,
                'daemon': thread.daemon,
                'alive': thread.is_alive()
            }
            threads.append(thread_info)
        
        # Count APScheduler threads
        apscheduler_threads = [t for t in threads if 'APScheduler' in t['name']]
        
        return jsonify({
            'scheduler_running': scheduler.scheduler.running if scheduler else False,
            'total_threads': len(threads),
            'apscheduler_threads': len(apscheduler_threads),
            'threads': threads
        }), 200
    except Exception as e:
        return jsonify({'error': f'Error getting scheduler status: {str(e)}'}), 500

def graceful_shutdown(signum, frame):
    """Handle graceful shutdown of the application"""
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    
    # Get the scheduler
    scheduler = app.config.get('SCHEDULER')
    if scheduler:
        scheduler.shutdown()
    
    # Exit the application
    exit(0)

@app.route('/debug-schedulers')
def debug_schedulers():
    """Debug endpoint to check for multiple scheduler instances"""
    import gc
    import inspect
    from apscheduler.schedulers.base import BaseScheduler
    
    # Find all scheduler instances
    schedulers = []
    for obj in gc.get_objects():
        if isinstance(obj, BaseScheduler):
            scheduler_info = {
                'type': type(obj).__name__,
                'running': obj.running if hasattr(obj, 'running') else 'unknown',
                'id': id(obj)
            }
            schedulers.append(scheduler_info)
    
    # Get the main scheduler
    main_scheduler = current_app.config.get('SCHEDULER')
    main_scheduler_id = id(main_scheduler.scheduler) if main_scheduler else None
    
    return jsonify({
        'main_scheduler_id': main_scheduler_id,
        'schedulers_found': len(schedulers),
        'schedulers': schedulers
    })

@app.route('/debug-job-triggers')
def debug_job_triggers():
    """Debug endpoint to check for custom job triggers"""
    import threading
    import traceback
    
    # Get all threads
    threads = []
    for thread in threading.enumerate():
        thread_info = {
            'name': thread.name,
            'daemon': thread.daemon,
            'alive': thread.is_alive(),
            'id': thread.ident
        }
        
        # Try to get the thread's stack trace
        if thread.ident:
            try:
                frame = sys._current_frames().get(thread.ident)
                if frame:
                    stack = traceback.format_stack(frame)
                    thread_info['stack'] = stack
            except Exception as e:
                thread_info['stack_error'] = str(e)
        
        threads.append(thread_info)
    
    # Check for timer threads
    timer_threads = [t for t in threads if 'Timer' in t['name']]
    
    return jsonify({
        'total_threads': len(threads),
        'timer_threads': len(timer_threads),
        'threads': threads
    })

@app.route('/complete-shutdown', methods=['POST'])
def complete_shutdown():
    """Endpoint to completely shut down all job triggers"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        # Shutdown the main scheduler
        if scheduler.scheduler.running:
            # First pause all jobs
            for job in scheduler.scheduler.get_jobs():
                job.pause()
            logger.info("All jobs paused before shutdown")
            
            # Remove all jobs
            scheduler.scheduler.remove_all_jobs()
            logger.info("All jobs removed from scheduler")
            
            # Shutdown the scheduler
            scheduler.scheduler.shutdown(wait=True)
            logger.info("Main scheduler shutdown complete")
        
        # Find and shutdown all other schedulers
        import gc
        from apscheduler.schedulers.base import BaseScheduler
        
        other_schedulers_shutdown = 0
        for obj in gc.get_objects():
            if isinstance(obj, BaseScheduler) and obj is not scheduler.scheduler:
                if hasattr(obj, 'running') and obj.running:
                    obj.shutdown(wait=True)
                    other_schedulers_shutdown += 1
        
        # Cancel all timers
        import threading
        timers_cancelled = 0
        for thread in threading.enumerate():
            if isinstance(thread, threading.Timer) and thread.is_alive():
                thread.cancel()
                timers_cancelled += 1
        
        # Clear all job locks
        for job_id, lock in scheduler.job_locks.items():
            if lock.locked():
                try:
                    lock.release()
                    logger.info(f"Released lock for job {job_id}")
                except RuntimeError:
                    # Lock might be owned by a different thread
                    pass
        scheduler.job_locks = {}
        
        # Force garbage collection
        gc.collect()
        
        # Verify shutdown
        import threading
        apscheduler_threads = [t for t in threading.enumerate() if 'APScheduler' in t.name]
        
        return jsonify({
            'message': 'Complete shutdown successful',
            'main_scheduler_shutdown': True,
            'other_schedulers_shutdown': other_schedulers_shutdown,
            'timers_cancelled': timers_cancelled,
            'lingering_apscheduler_threads': len(apscheduler_threads)
        }), 200
    except Exception as e:
        logger.error(f"Error during complete shutdown: {e}")
        return jsonify({'error': f'Error during complete shutdown: {str(e)}'}), 500

@app.route('/scheduler-health-check')
def scheduler_health_check():
    """Comprehensive health check for the scheduler"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'status': 'error', 'message': 'Scheduler not initialized'}), 500
    
    try:
        # Check if scheduler is running
        scheduler_running = scheduler.scheduler.running
        
        # Check executors
        executor_status = {}
        for executor_name, executor in scheduler.scheduler._executors.items():
            if hasattr(executor, '_pool'):
                # Safely get queue size without accessing .queue directly
                queue_size = 'unknown'
                try:
                    if hasattr(executor._pool, '_work_queue'):
                        # Use qsize() method if available
                        if hasattr(executor._pool._work_queue, 'qsize'):
                            queue_size = executor._pool._work_queue.qsize()
                        # For SimpleQueue which doesn't have qsize()
                        else:
                            queue_size = 'unavailable'
                except (NotImplementedError, AttributeError):
                    # Some queue implementations don't support qsize()
                    queue_size = 'unsupported'
                
                executor_status[executor_name] = {
                    'shutdown': executor._pool._shutdown,
                    'threads': executor._pool._max_workers,
                    'queue_size': queue_size
                }
        
        # Check job locks
        lock_status = {}
        for job_id, lock in scheduler.job_locks.items():
            lock_status[job_id] = lock.locked()
        
        # Get job information
        jobs = []
        for job in scheduler.scheduler.get_jobs():
            job_info = {
                'id': job.id,
                'next_run_time': str(job.next_run_time) if job.next_run_time else None,
                'trigger': str(job.trigger)
            }
            jobs.append(job_info)
        
        # Get thread information
        import threading
        threads = []
        for thread in threading.enumerate():
            thread_info = {
                'name': thread.name,
                'daemon': thread.daemon,
                'alive': thread.is_alive()
            }
            threads.append(thread_info)
        
        # Get recent job executions
        from models import JobExecution
        recent_executions = JobExecution.query.order_by(JobExecution.start_time.desc()).limit(10).all()
        executions = []
        for execution in recent_executions:
            executions.append({
                'job_id': execution.job_id,
                'start_time': execution.start_time.isoformat() if execution.start_time else None,
                'end_time': execution.end_time.isoformat() if execution.end_time else None,
                'status': execution.status,
                'execution_time': execution.execution_time
            })
        
        return jsonify({
            'status': 'ok' if scheduler_running else 'error',
            'running': scheduler_running,
            'executors': executor_status,
            'job_locks': lock_status,
            'jobs': jobs,
            'threads': threads,
            'recent_executions': executions,
            'health_metrics': scheduler.health_check.get_health_status()
        })
    except Exception as e:
        logger.error(f"Error in scheduler health check: {e}")
        return jsonify({'status': 'error', 'message': f'Error in scheduler health check: {str(e)}'}), 500

@app.route('/debug-job-execution', methods=['POST'])
def debug_job_execution():
    """Debug endpoint to trace job execution sources"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        # Enable detailed job execution tracing
        import sys
        import traceback
        import threading
        
        # Add a hook to trace job function calls
        original_functions = {}
        
        def trace_job_execution(job_id, original_func):
            def traced_func(*args, **kwargs):
                thread_id = threading.get_ident()
                stack = ''.join(traceback.format_stack())
                logger.critical(f"JOB TRACE: {job_id} called in thread {thread_id}\nStack trace:\n{stack}")
                return original_func(*args, **kwargs)
            return traced_func
        
        # Replace job functions with traced versions
        for job_id, job_config in scheduler.jobs.items():
            if isinstance(job_config, dict) and 'original_func' in job_config:
                original_functions[job_id] = job_config['original_func']
                job_config['original_func'] = trace_job_execution(job_id, job_config['original_func'])
                logger.info(f"Added execution tracing to job {job_id}")
        
        return jsonify({
            'message': 'Job execution tracing enabled',
            'jobs_traced': list(original_functions.keys())
        }), 200
    except Exception as e:
        logger.error(f"Error setting up job execution tracing: {e}")
        return jsonify({'error': f'Error setting up job execution tracing: {str(e)}'}), 500

@app.route('/check-other-schedulers')
def check_other_schedulers():
    """Check for other scheduling mechanisms"""
    try:
        import os
        import subprocess
        import threading
        
        # Check for cron jobs
        cron_output = "Not available"
        try:
            cron_output = subprocess.check_output("crontab -l", shell=True, stderr=subprocess.STDOUT).decode('utf-8')
        except subprocess.CalledProcessError:
            cron_output = "No crontab for current user"
        
        # Check for systemd timers
        systemd_timers = "Not available"
        try:
            systemd_timers = subprocess.check_output("systemctl list-timers", shell=True, stderr=subprocess.STDOUT).decode('utf-8')
        except subprocess.CalledProcessError:
            systemd_timers = "Could not check systemd timers"
        
        # Check for threading.Timer instances
        timer_threads = []
        for thread in threading.enumerate():
            if isinstance(thread, threading.Timer):
                timer_threads.append({
                    'name': thread.name,
                    'interval': thread.interval if hasattr(thread, 'interval') else 'unknown',
                    'function': str(thread.function) if hasattr(thread, 'function') else 'unknown'
                })
        
        # Check for any modules that might be scheduling tasks
        import sys
        scheduling_modules = []
        for module_name in sys.modules:
            if any(name in module_name for name in ['sched', 'schedule', 'timer', 'cron', 'periodic']):
                scheduling_modules.append(module_name)
        
        return jsonify({
            'cron_jobs': cron_output,
            'systemd_timers': systemd_timers,
            'timer_threads': timer_threads,
            'scheduling_modules': scheduling_modules
        }), 200
    except Exception as e:
        return jsonify({'error': f'Error checking for other schedulers: {str(e)}'}), 500

@app.route('/check-direct-calls')
def check_direct_calls():
    """Check for direct function calls"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        # Get all job functions
        job_functions = {}
        for job_id, job_config in scheduler.jobs.items():
            if isinstance(job_config, dict):
                if 'original_func' in job_config:
                    job_functions[job_id] = {
                        'name': job_config['original_func'].__name__,
                        'module': job_config['original_func'].__module__
                    }
                elif 'func' in job_config:
                    job_functions[job_id] = {
                        'name': job_config['func'].__name__,
                        'module': job_config['func'].__module__
                    }
        
        # Check for imports of these functions
        import sys
        import inspect
        
        direct_calls = {}
        for module_name, module in sys.modules.items():
            if not module or not hasattr(module, '__dict__'):
                continue
            
            for attr_name, attr_value in module.__dict__.items():
                if callable(attr_value) and hasattr(attr_value, '__name__'):
                    for job_id, func_info in job_functions.items():
                        if (attr_value.__name__ == func_info['name'] and 
                            attr_value.__module__ == func_info['module']):
                            # Found a reference to a job function
                            if job_id not in direct_calls:
                                direct_calls[job_id] = []
                            direct_calls[job_id].append({
                                'module': module_name,
                                'attribute': attr_name
                            })
        
        return jsonify({
            'job_functions': job_functions,
            'direct_calls': direct_calls
        }), 200
    except Exception as e:
        return jsonify({'error': f'Error checking for direct calls: {str(e)}'}), 500

@app.route('/scheduler-complete-reset', methods=['POST'])
def scheduler_complete_reset():
    """Completely reset the scheduler system by removing all instances and creating a new one"""
    try:
        # Step 1: Find and shut down all scheduler instances
        import gc
        from apscheduler.schedulers.base import BaseScheduler
        
        # Get the main scheduler
        main_scheduler = current_app.config.get('SCHEDULER')
        
        # Shut down the main scheduler if it exists
        if main_scheduler and main_scheduler.scheduler.running:
            logger.info("Shutting down main scheduler...")
            main_scheduler.shutdown()
        
        # Find and shut down all other schedulers
        other_schedulers_shutdown = 0
        for obj in gc.get_objects():
            if isinstance(obj, BaseScheduler) and (not main_scheduler or obj is not main_scheduler.scheduler):
                if hasattr(obj, 'running') and obj.running:
                    logger.info(f"Shutting down additional scheduler instance: {id(obj)}")
                    obj.shutdown(wait=True)
                    other_schedulers_shutdown += 1
        
        # Step 2: Create a completely new scheduler
        from scheduler import FlaskJobScheduler
        
        # Create a new scheduler instance
        new_scheduler = FlaskJobScheduler(current_app)
        
        # Replace the old scheduler in the app config
        current_app.config['SCHEDULER'] = new_scheduler
        
        # Step 3: Initialize the new scheduler with jobs
        with current_app.app_context():
            from scheduler_config import initialize_scheduler
            initialize_scheduler(current_app, new_scheduler)
        
        # Step 4: Start the new scheduler
        new_scheduler.start()
        
        # Step 5: Force garbage collection to clean up old instances
        gc.collect()
        
        # Verify the reset
        schedulers_after = []
        for obj in gc.get_objects():
            if isinstance(obj, BaseScheduler):
                schedulers_after.append({
                    'id': id(obj),
                    'running': obj.running if hasattr(obj, 'running') else 'unknown'
                })
        
        return jsonify({
            'message': 'Scheduler system completely reset',
            'other_schedulers_shutdown': other_schedulers_shutdown,
            'new_scheduler_id': id(new_scheduler.scheduler),
            'new_scheduler_running': new_scheduler.scheduler.running,
            'schedulers_after_reset': schedulers_after
        }), 200
    except Exception as e:
        logger.error(f"Error during complete scheduler reset: {e}")
        return jsonify({'error': f'Error during complete scheduler reset: {str(e)}'}), 500

# Register signal handlers
signal.signal(signal.SIGTERM, graceful_shutdown)
signal.signal(signal.SIGINT, graceful_shutdown)

def cleanup_on_exit():
    """Clean up resources when the application exits"""
    # Only clean up during actual application shutdown, not after each request
    if not app.config.get('_CLEANUP_CALLED', False):
        logger.info("Application teardown: cleaning up resources")
        
        # Get the scheduler
        scheduler = app.config.get('SCHEDULER')
        if scheduler and hasattr(scheduler, 'scheduler') and scheduler.scheduler.running:
            logger.info("Shutting down scheduler during application teardown")
            try:
                scheduler.shutdown()
                app.config['_CLEANUP_CALLED'] = True
            except Exception as e:
                logger.error(f"Error shutting down scheduler during teardown: {e}")

# Update how you register the teardown function
import atexit
atexit.register(cleanup_on_exit)

# Test log messages
logger.debug("This is a debug message TEST")
logger.info("This is an info message")
logger.warning("This is a warning message")
logger.error("This is an error message")
logger.critical("This is a critical message")

if __name__ == '__main__':
    logger.info("Starting application...")
    with app.app_context():
        logger.info("Initializing database tables...")
        init_db()  # Initialize database tables
        logger.info("Database initialization complete")
    
    # Force enable hot reload for development
    debug_mode = True  # Set to True to force enable debug mode
    use_reloader = True  # Set to True to force enable reloader
    
    # Log the debug and reloader settings
    logger.info(f"Starting Flask with debug={debug_mode}, use_reloader={use_reloader}")
    
    app.run(
        host='0.0.0.0', 
        port=5056, 
        debug=debug_mode, 
        use_reloader=use_reloader,
        # Add these options to improve reloader behavior
        threaded=True,
        extra_files=None  # Let Flask automatically detect files to watch
    )