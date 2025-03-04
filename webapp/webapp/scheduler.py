# scheduler.py
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from datetime import datetime
import pytz
from functools import wraps
import atexit
import threading
from flask import current_app

logger = logging.getLogger('webapp logger')

class SchedulerHealthCheck:
    """Class to track scheduler health metrics"""
    
    def __init__(self):
        self.last_success = None
        self.last_failure = None
        self.failure_count = 0
        self.total_executions = 0
        self.total_execution_time = 0
        self.average_execution_time = 0
    
    def record_success(self, execution_time):
        """Record a successful job execution"""
        self.last_success = datetime.now(pytz.timezone('Etc/UTC'))
        self.total_executions += 1
        self.total_execution_time += execution_time
        self.average_execution_time = self.total_execution_time / self.total_executions
    
    def record_failure(self):
        """Record a failed job execution"""
        self.last_failure = datetime.now(pytz.timezone('Etc/UTC'))
        self.failure_count += 1
        self.total_executions += 1
    
    def get_health_status(self):
        """Get the current health status"""
        return {
            'last_success': self.last_success,
            'last_failure': self.last_failure,
            'failure_count': self.failure_count,
            'total_executions': self.total_executions,
            'average_execution_time': self.average_execution_time
        }

class FlaskJobScheduler:
    """Scheduler for Flask background jobs"""
    
    # Class variable to track instances
    _instances = {}
    
    def __new__(cls, app=None):
        """Ensure only one instance per app"""
        # Use a class variable to track the single instance
        if not hasattr(cls, '_instance') or cls._instance is None:
            cls._instance = super(FlaskJobScheduler, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self, app=None):
        """Initialize the scheduler"""
        # Skip initialization if already initialized
        if hasattr(self, 'initialized') and self.initialized:
            if app is not None and self.app is not app:
                # If a different app is provided, update the app reference
                self.app = app
                app.config['SCHEDULER'] = self
            return
            
        self.app = None
        self.jobs = {}
        self.health_check = SchedulerHealthCheck()
        self.job_locks = {}  # Dictionary to store locks for each job
        
        # Configure the scheduler
        executors = {
            'default': ThreadPoolExecutor(20)
        }
        job_defaults = {
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 60
        }
        self.scheduler = BackgroundScheduler(
            executors=executors,
            job_defaults=job_defaults,
            timezone=pytz.timezone('Etc/UTC'),
            daemon=False
        )
        
        # If app is provided, initialize with app
        if app:
            self.init_app(app)
        
        self.initialized = True
    
    def init_app(self, app):
        """Initialize the scheduler with a Flask application"""
        if self.app is not None:
            raise RuntimeError("Flask scheduler is already initialized")
            
        self.app = app
        
        # Store the scheduler in the app config
        app.config['SCHEDULER'] = self
        
        # Register shutdown function with atexit
        atexit.register(self.shutdown)
    
    def _create_app_context_job(self, job_id, func):
        """Create a job function that runs within an application context"""
        # Create a lock for this job if it doesn't exist
        if job_id not in self.job_locks:
            self.job_locks[job_id] = threading.Lock()
        
        @wraps(func)
        def app_context_job(*args, **kwargs):
            # Import here to avoid circular imports
            from models import db, JobExecution
            import time
            import flask
            from flask import Flask

            # Check if scheduler is running
            if not self.scheduler.running:
                logger.warning(f"Job {job_id} execution prevented - scheduler is not running")
                return False
            
            # Generate a unique execution ID for this run
            import uuid
            execution_id = str(uuid.uuid4())
            
            # Try to acquire the lock, but don't block if we can't
            if not self.job_locks[job_id].acquire(blocking=False):
                logger.warning(f"Job {job_id} is already running (lock is held). Skipping this execution.")
                return False
            
            thread_id = threading.get_ident()
            logger.info(f"Job {job_id} acquired lock in thread {thread_id} (execution_id={execution_id})")
            
            try:
                start_time = time.time()
                
                # Create a fresh application context for this job
                from app import app as flask_app
                
                # Create an application context
                with flask_app.app_context():
                    # Check if this job is already running in the database
                    running_job = JobExecution.query.filter_by(
                        job_id=job_id, 
                        status='running'
                    ).first()
                    
                    if running_job:
                        # If the job has been running for more than 5 minutes, consider it stale
                        now = datetime.now(pytz.timezone('Etc/UTC'))
                        # Ensure both datetimes are timezone-aware
                        if running_job.start_time.tzinfo is None:
                            # If start_time is naive, make it aware
                            aware_start_time = pytz.timezone('Etc/UTC').localize(running_job.start_time)
                        else:
                            aware_start_time = running_job.start_time
                            
                        running_time = (now - aware_start_time).total_seconds()
                        
                        if running_time < 300:  # 5 minutes in seconds
                            logger.warning(f"Job {job_id} is already running in DB (started {running_time:.1f} seconds ago). Skipping this execution.")
                            return False
                        else:
                            logger.warning(f"Job {job_id} has been running for {running_time:.1f} seconds. Marking as failed and starting new execution.")
                            running_job.status = 'failed'
                            running_job.end_time = now
                            running_job.error_message = 'Job execution timed out'
                            db.session.commit()
                    
                    # Create job execution record
                    job_execution = JobExecution(
                        job_id=job_id,
                        start_time=datetime.now(pytz.timezone('Etc/UTC')),
                        status='running'
                    )
                    
                    try:
                        db.session.add(job_execution)
                        db.session.commit()
                        logger.info(f"Created job execution record for {job_id}")
                    except Exception as e:
                        db.session.rollback()
                        logger.error(f"Error creating job execution record: {e}")
                        # Continue with job execution even if recording fails
                    
                    try:
                        # Execute the job function
                        logger.info(f"Running {job_id} job")
                        result = func(*args, **kwargs)
                        end_time = time.time()
                        execution_time = end_time - start_time
                        
                        # Update job execution record
                        try:
                            job_execution.end_time = datetime.now(pytz.timezone('Etc/UTC'))
                            job_execution.status = 'success'
                            job_execution.execution_time = execution_time
                            db.session.commit()
                            logger.info(f"Updated job execution record for {job_id} (success)")
                        except Exception as e:
                            logger.error(f"Error updating job execution record: {e}")
                        
                        # Update health check
                        self.health_check.record_success(execution_time)
                        logger.info(f"Updated health metrics for job {job_id}: success")
                        
                        logger.info(f"Job {job_id} completed in {execution_time:.2f} seconds")
                        return result
                    except Exception as e:
                        # Update job execution record with error
                        try:
                            job_execution.end_time = datetime.now(pytz.timezone('Etc/UTC'))
                            job_execution.status = 'failed'
                            job_execution.error_message = str(e)
                            db.session.commit()
                            logger.info(f"Updated job execution record for {job_id} (failed)")
                        except Exception as db_error:
                            logger.error(f"Error updating job execution record: {db_error}")
                        
                        # Update health check
                        self.health_check.record_failure()
                        logger.info(f"Updated health metrics for job {job_id}: failure")
                        
                        logger.error(f"Job {job_id} failed: {str(e)}")
                        raise
            finally:
                # Always release the lock, even if an exception occurs
                self.job_locks[job_id].release()
                logger.info(f"Job {job_id} released lock in thread {thread_id}")
        
        return app_context_job
    
    def add_job(self, job_id, func, trigger, **trigger_args):
        """Add a job to the scheduler"""
        if not self.app:
            raise ValueError("Scheduler not initialized with app")
        
        # Create a lock for this job if it doesn't exist
        if job_id not in self.job_locks:
            self.job_locks[job_id] = threading.Lock()
        
        # Wrap the job function with execution tracking
        tracked_func = self._job_wrapper(job_id, func)
        
        # Wrap the job function with application context
        wrapped_func = self._create_app_context_job(job_id, tracked_func)
        
        # Add the job to the scheduler
        job = self.scheduler.add_job(
            func=wrapped_func,
            trigger=trigger,
            **trigger_args,
            id=job_id,
            replace_existing=True
        )
        
        # Store job configuration for later recreation
        self.jobs[job_id] = {
            'func': wrapped_func,
            'trigger': trigger,
            'trigger_args': trigger_args,
            'original_func': func  # Store the original function for reference
        }
        
        return job
    
    def start(self):
        """Start the scheduler with a fresh executor"""
        try:
            if self.scheduler.running:
                logger.info("Scheduler already running, shutting down first...")
                self.scheduler.shutdown(wait=True)
            
            # Create fresh executors
            from concurrent.futures import ThreadPoolExecutor
            executors = {
                'default': {
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
            
            self.scheduler = BackgroundScheduler(
                executors=executors,
                job_defaults=job_defaults,
                timezone=pytz.timezone('Etc/UTC'),
                daemon=False
            )
            
            # Re-add all jobs to the new scheduler
            for job_id, job_config in self.jobs.items():
                # Add the job to the new scheduler
                new_job = self.scheduler.add_job(
                    func=job_config['func'],
                    trigger=job_config['trigger'],
                    **job_config['trigger_args'],
                    id=job_id,
                    replace_existing=True
                )
            
            logger.info("Starting scheduler with fresh executors...")
            self.scheduler.start()
            logger.info(f"Scheduler started successfully. Running: {self.scheduler.running}")
            return True
        except Exception as e:
            logger.error(f"Error starting scheduler: {e}")
            return False
    
    def shutdown(self):
        """Shutdown the scheduler completely"""
        try:
            if self.scheduler.running:
                logger.info("Shutting down scheduler...")
                
                # First pause all jobs to prevent new executions
                for job in self.scheduler.get_jobs():
                    job.pause()
                logger.info("All jobs paused before shutdown")
                
                # Wait a moment for any in-progress job submissions to complete
                import time
                time.sleep(1)
                
                # Remove all jobs from the scheduler
                self.scheduler.remove_all_jobs()
                logger.info("All jobs removed from scheduler")
                
                # Now shutdown with wait=True to ensure clean shutdown
                self.scheduler.shutdown(wait=True)
                logger.info("Scheduler shutdown complete")
                
                # Clear all job locks
                for job_id, lock in self.job_locks.items():
                    if lock.locked():
                        try:
                            lock.release()
                            logger.info(f"Released lock for job {job_id}")
                        except RuntimeError:
                            # Lock might be owned by a different thread
                            pass
                self.job_locks = {}
                
                # Force garbage collection to clean up any lingering references
                import gc
                gc.collect()
                
                return True
            else:
                logger.info("Scheduler already stopped")
                return True
        except Exception as e:
            logger.error(f"Error shutting down scheduler: {e}")
            return False
            
    def get_jobs(self):
        """Get all jobs"""
        return {job_id: str(job) for job_id, job in self.jobs.items()}
    
    def get_job_statuses(self):
        """Get the status of all jobs (paused or active)"""
        statuses = {}
        for job_id in self.jobs.keys():
            apscheduler_job = self.scheduler.get_job(job_id)
            if apscheduler_job:
                # Safely check if next_run_time attribute exists
                if hasattr(apscheduler_job, 'next_run_time'):
                    statuses[job_id] = 'paused' if apscheduler_job.next_run_time is None else 'active'
                else:
                    statuses[job_id] = 'unknown (no next_run_time attribute)'
            else:
                statuses[job_id] = 'unknown (job not found in scheduler)'
        return statuses
    
    def remove_all_jobs(self):
        """Remove all jobs from the scheduler"""
        try:
            # Remove all jobs from the APScheduler
            self.scheduler.remove_all_jobs()
            # Clear our jobs dictionary
            self.jobs = {}
            logger.info("All jobs removed from scheduler")
        except Exception as e:
            logger.error(f"Error removing jobs: {e}")
    
    def _job_wrapper(self, job_id, func):
        """Wrapper for job functions to add execution tracking"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            import threading
            import traceback
            
            thread_id = threading.get_ident()
            logger.info(f"Job {job_id} started in thread {thread_id}")
            logger.debug(f"Job {job_id} call stack:\n{traceback.format_stack()}")
            
            try:
                result = func(*args, **kwargs)
                logger.info(f"Job {job_id} completed successfully in thread {thread_id}")
                return result
            except Exception as e:
                logger.error(f"Job {job_id} failed in thread {thread_id}: {e}")
                logger.error(traceback.format_exc())
                raise
        
        return wrapper