# blueprints/scheduler.py
from flask import Blueprint, render_template, jsonify, current_app, request
import logging
from datetime import datetime
import pytz
import time  
from models import JobExecution

logger = logging.getLogger('webapp logger')

scheduler_bp = Blueprint('scheduler', __name__, url_prefix='/scheduler')

@scheduler_bp.route('/')
def scheduler_dashboard():
    """Scheduler dashboard showing system status."""
    scheduler = current_app.config.get('SCHEDULER')
    ibkr_client = current_app.config.get('IBKR_CLIENT')
    
    # Get scheduler status
    scheduler_running = scheduler.scheduler.running if scheduler else False
    scheduler_jobs = scheduler.get_jobs() if scheduler else {}
    health_status = scheduler.health_check.get_health_status() if scheduler else {}
    
    # Get job statuses (paused or active)
    job_statuses = scheduler.get_job_statuses() if scheduler else {}
    
    # Get IBKR connection status
    ibkr_connected = False
    auth_status = {}
    if ibkr_client:
        session_data = ibkr_client.get_session_status()
        if session_data:
            iserver_data = session_data.get('iserver', {})
            auth_status = iserver_data.get('authStatus', {})
            ibkr_connected = auth_status.get('authenticated', False)
    
    # Get next run times for jobs
    next_run_times = {}
    if scheduler:
        for job_id in scheduler_jobs.keys():
            # Get the APScheduler job object
            apscheduler_job = scheduler.scheduler.get_job(job_id)
            if apscheduler_job and hasattr(apscheduler_job, 'next_run_time'):
                next_run_times[job_id] = apscheduler_job.next_run_time
    
    return render_template('scheduler.html',
                          scheduler_running=scheduler_running,
                          scheduler_jobs=scheduler_jobs,
                          health_status=health_status,
                          ibkr_connected=ibkr_connected,
                          auth_status=auth_status,
                          next_run_times=next_run_times,
                          job_statuses=job_statuses)

@scheduler_bp.route('/jobs', methods=['GET'])
def list_jobs():
    """API endpoint to get job information."""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    # Get all jobs
    jobs = scheduler.get_jobs()
    
    # Get next run times
    next_run_times = {}
    for job_id in jobs.keys():
        job = scheduler.scheduler.get_job(job_id)
        if job and job.next_run_time:
            next_run_times[job_id] = job.next_run_time.isoformat()
    
    return jsonify({
        'jobs': jobs,
        'next_run_times': next_run_times,
        'health': scheduler.health_check.get_health_status(),
        'running': scheduler.scheduler.running
    })

@scheduler_bp.route('/health', methods=['GET'])
def health_check():
    """API endpoint to get scheduler health information."""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    return jsonify(scheduler.health_check.get_health_status())

@scheduler_bp.route('/job/<job_id>/run', methods=['POST'])
def run_job(job_id):
    """Run a job manually"""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    if job_id not in scheduler.jobs:
        return jsonify({'error': f'Job {job_id} not found'}), 404
    
    try:
        # Get the job configuration
        job_config = scheduler.jobs.get(job_id)
        
        # Check if job_config is a dictionary (new format)
        if isinstance(job_config, dict):
            if 'original_func' in job_config:
                # Use the original function if available
                func = job_config['original_func']
            elif 'func' in job_config:
                # Use the wrapped function if original is not available
                func = job_config['func']
            else:
                return jsonify({'error': f'Job {job_id} has invalid configuration'}), 500
                
            # Create a new execution record
            from models import JobExecution, db
            from datetime import datetime
            import pytz
            import time
            
            job_execution = JobExecution(
                job_id=job_id,
                start_time=datetime.now(pytz.timezone('Etc/UTC')),
                status='running'
            )
            
            try:
                db.session.add(job_execution)
                db.session.commit()
                logger.info(f"Created job execution record for manual run of {job_id}")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error creating job execution record: {e}")
            
            # Execute the function
            start_time = time.time()
            with current_app.app_context():
                result = func()
            end_time = time.time()
            execution_time = end_time - start_time
            
            # Update the execution record
            try:
                job_execution.end_time = datetime.now(pytz.timezone('Etc/UTC'))
                job_execution.status = 'success'
                job_execution.execution_time = execution_time
                db.session.commit()
                logger.info(f"Updated job execution record for manual run of {job_id}")
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error updating job execution record: {e}")
            
            return jsonify({
                'message': f'Job {job_id} executed successfully',
                'result': str(result),
                'execution_time': f'{execution_time:.2f} seconds'
            }), 200
        else:
            # Try to get the job from the scheduler
            apscheduler_job = scheduler.scheduler.get_job(job_id)
            if apscheduler_job and hasattr(apscheduler_job, 'func'):
                result = apscheduler_job.func()
                return jsonify({'message': f'Job {job_id} executed successfully', 'result': str(result)}), 200
            else:
                logger.error(f"Error running job {job_id}: Job object doesn't have expected structure")
                return jsonify({'error': f'Error running job {job_id}: Job object has unexpected structure'}), 500
    except Exception as e:
        logger.error(f"Error running job {job_id}: {e}")
        return jsonify({'error': f'Error running job {job_id}: {str(e)}'}), 500

@scheduler_bp.route('/job/<job_id>/pause', methods=['POST'])
def pause_job(job_id):
    """API endpoint to pause a job."""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    if job_id not in scheduler.jobs:
        return jsonify({'error': f'Job {job_id} not found'}), 404
    
    try:
        # Pause the job
        scheduler.scheduler.pause_job(job_id)
        return jsonify({'message': f'Job {job_id} paused successfully'}), 200
    except Exception as e:
        logger.error(f"Error pausing job {job_id}: {e}")
        return jsonify({'error': f'Error pausing job: {str(e)}'}), 500

@scheduler_bp.route('/job/<job_id>/resume', methods=['POST'])
def resume_job(job_id):
    """API endpoint to resume a job."""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    if job_id not in scheduler.jobs:
        return jsonify({'error': f'Job {job_id} not found'}), 404
    
    try:
        # Resume the job
        scheduler.scheduler.resume_job(job_id)
        return jsonify({'message': f'Job {job_id} resumed successfully'}), 200
    except Exception as e:
        logger.error(f"Error resuming job {job_id}: {e}")
        return jsonify({'error': f'Error resuming job: {str(e)}'}), 500

@scheduler_bp.route('/history')
def job_history():
    """View job execution history."""
    # Get recent job executions
    executions = JobExecution.get_recent_executions(limit=100)
    
    # Get job statistics
    job_stats = {}
    for execution in executions:
        if execution.job_id not in job_stats:
            job_stats[execution.job_id] = {
                'total': 0,
                'success': 0,
                'failed': 0,
                'running': 0,
                'avg_time': 0,
                'total_time': 0
            }
        
        job_stats[execution.job_id]['total'] += 1
        job_stats[execution.job_id][execution.status] += 1
        
        if execution.execution_time:
            job_stats[execution.job_id]['total_time'] += execution.execution_time
    
    # Calculate average execution time
    for job_id, stats in job_stats.items():
        if stats['success'] > 0:
            stats['avg_time'] = stats['total_time'] / stats['success']
    
    return render_template('scheduler_history.html', 
                        executions=executions,
                        job_stats=job_stats)

@scheduler_bp.route('/history/<job_id>')
def job_detail_history(job_id):
    """View execution history for a specific job."""
    # Get recent job executions for this job
    executions = JobExecution.get_executions_by_job_id(job_id, limit=100)
    
    # Calculate statistics
    total = len(executions)
    success = sum(1 for e in executions if e.status == 'success')
    failed = sum(1 for e in executions if e.status == 'failed')
    running = sum(1 for e in executions if e.status == 'running')
    
    # Calculate average execution time
    success_times = [e.execution_time for e in executions if e.status == 'success' and e.execution_time]
    avg_time = sum(success_times) / len(success_times) if success_times else 0
    
    return render_template('scheduler_job_history.html',
                        job_id=job_id,
                        executions=executions,
                        total=total,
                        success=success,
                        failed=failed,
                        running=running,
                        avg_time=avg_time)

@scheduler_bp.route('/start', methods=['POST'])
def start_scheduler():
    """API endpoint to start the scheduler."""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        if not scheduler.scheduler.running:
            # Reinitialize the scheduler with jobs
            from scheduler_config import initialize_scheduler
            initialize_scheduler(current_app, scheduler)
            
            # If still not running, start it explicitly
            if not scheduler.scheduler.running:
                scheduler.start()
                
            return jsonify({'message': 'Scheduler started successfully'}), 200
        else:
            return jsonify({'message': 'Scheduler is already running'}), 200
    except Exception as e:
        logger.error(f"Error starting scheduler: {e}")
        return jsonify({'error': f'Error starting scheduler: {str(e)}'}), 500

@scheduler_bp.route('/stop', methods=['POST'])
def stop_scheduler():
    """API endpoint to stop the scheduler."""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    try:
        if scheduler.scheduler.running:
            scheduler.scheduler.shutdown()
            return jsonify({'message': 'Scheduler stopped successfully'}), 200
        else:
            return jsonify({'message': 'Scheduler is not running'}), 200
    except Exception as e:
        logger.error(f"Error stopping scheduler: {e}")
        return jsonify({'error': f'Error stopping scheduler: {str(e)}'}), 500
    
@scheduler_bp.route('/job-statuses', methods=['GET'])
def get_job_statuses():
    """API endpoint to get the status of all jobs."""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    job_statuses = scheduler.get_job_statuses()
    return jsonify({'job_statuses': job_statuses})

@scheduler_bp.route('/debug-health', methods=['GET'])
def debug_health():
    """Debug endpoint to check health metrics."""
    scheduler = current_app.config.get('SCHEDULER')
    if not scheduler:
        return jsonify({'error': 'Scheduler not initialized'}), 500
    
    # Get health metrics directly from the scheduler
    health_metrics = scheduler.health_check.get_health_status()
    
    # Get job execution records from database
    from models import JobExecution
    executions = JobExecution.query.order_by(JobExecution.start_time.desc()).limit(10).all()
    
    # Format executions for JSON
    formatted_executions = []
    for execution in executions:
        formatted_executions.append({
            'job_id': execution.job_id,
            'start_time': execution.start_time.isoformat() if execution.start_time else None,
            'end_time': execution.end_time.isoformat() if execution.end_time else None,
            'status': execution.status,
            'execution_time': execution.execution_time
        })
    
    return jsonify({
        'health_metrics': health_metrics,
        'recent_executions': formatted_executions
    })