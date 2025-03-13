import os
from celery import Celery
from django.conf import settings
from celery.signals import task_failure, task_success, task_retry
import logging

logger = logging.getLogger(__name__)

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# Namespace configuration with prefix to avoid collisions
app.config_from_object('django.conf:settings', namespace='CELERY')

# Configure task routing
app.conf.task_routes = {
    # High priority tasks
    'apps.chat.tasks.process_message': {'queue': 'high_priority'},
    'apps.whatsapp.tasks.handle_whatsapp_message': {'queue': 'high_priority'},
    
    # Background tasks
    'apps.chat.tasks.cleanup_stale_messages': {'queue': 'maintenance'},
    'apps.chat.tasks.update_conversation_analytics': {'queue': 'analytics'},
    
    # Default queue for all other tasks
    '*': {'queue': 'default'},
}

# Performance optimizations
app.conf.update(
    worker_prefetch_multiplier=1,  # Prevent worker from prefetching too many tasks
    task_acks_late=True,  # Only acknowledge task completion after success
    task_time_limit=300,  # 5 minute timeout for tasks
    task_soft_time_limit=240,  # Soft timeout 4 minutes
    task_default_rate_limit='1000/m',  # Default rate limit
    worker_max_tasks_per_child=1000,  # Restart worker after 1000 tasks
    broker_transport_options={
        'visibility_timeout': 3600,  # 1 hour
        'max_retries': 3,
    },
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)

# Task monitoring and logging
@task_failure.connect
def handle_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    """Log task failures and potentially trigger alerts"""
    logger.error(
        f"Task {sender.name} ({task_id}) failed: {str(exception)}",
        exc_info=True
    )

@task_success.connect
def handle_task_success(sender=None, **kwargs):
    """Log successful task completion for monitoring"""
    logger.info(f"Task {sender.name} completed successfully")

@task_retry.connect
def handle_task_retry(sender=None, reason=None, **kwargs):
    """Log task retries for monitoring"""
    logger.warning(f"Task {sender.name} being retried: {str(reason)}")

# Auto-discover tasks in all installed apps
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)

@app.task(bind=True)
def debug_task(self):
    """Task for testing celery configuration"""
    print(f'Request: {self.request!r}')
