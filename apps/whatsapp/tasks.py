import logging
from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from django.core.cache import cache
from django.utils import timezone
from .services import WhatsAppService
from .models import WhatsAppMessage
from apps.chat.tasks import process_message

logger = logging.getLogger(__name__)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def handle_whatsapp_message(self, message_data):
    """
    Process incoming WhatsApp messages from webhook.
    Includes deduplication and proper error handling.
    """
    try:
        message_id = message_data.get('id')
        
        # Prevent duplicate processing using distributed lock
        lock_id = f'whatsapp_msg_{message_id}'
        if not cache.add(lock_id, 'true', timeout=300):  # 5 minute lock
            logger.info(f"Message {message_id} already being processed")
            return
            
        try:
            whatsapp_service = WhatsAppService()
            user_message, conversation = whatsapp_service.handle_incoming_message(
                sender_phone=message_data.get('from'),
                message_content=message_data.get('content'),
                message_sid=message_id
            )
            
            if user_message and conversation:
                # Process the message through our chat system
                process_message.delay(
                    user_message.id,
                    source='whatsapp'
                )
                logger.info(f"Successfully queued WhatsApp message {message_id} for processing")
                
        finally:
            cache.delete(lock_id)
            
    except Exception as e:
        logger.error(f"Error processing WhatsApp message: {str(e)}")
        try:
            self.retry(exc=e)
        except MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for message {message_data.get('id')}")
            # Update message status if possible
            try:
                whatsapp_message = WhatsAppMessage.objects.get(message_id=message_data.get('id'))
                whatsapp_message.mark_failed(str(e))
            except WhatsAppMessage.DoesNotExist:
                pass
            raise

@shared_task(bind=True)
def update_message_status(self, message_id, new_status):
    """
    Update WhatsApp message delivery status.
    Used for handling status update webhooks.
    """
    try:
        message = WhatsAppMessage.objects.get(message_id=message_id)
        
        if new_status == 'delivered':
            message.mark_delivered()
        elif new_status == 'read':
            message.mark_read()
        elif new_status == 'failed':
            message.mark_failed("Delivery failed according to webhook")
            
        logger.info(f"Updated status for message {message_id} to {new_status}")
        
    except WhatsAppMessage.DoesNotExist:
        logger.error(f"Message {message_id} not found for status update")
    except Exception as e:
        logger.error(f"Error updating message status: {str(e)}")
        raise

@shared_task(
    bind=True,
    rate_limit='60/m'
)
def cleanup_stale_whatsapp_messages(self):
    """
    Cleanup task to handle stale WhatsApp messages.
    Marks messages as failed if they haven't been delivered after timeout.
    """
    try:
        # Find messages stuck in SENT status
        timeout = timezone.now() - timezone.timedelta(hours=24)
        stale_messages = WhatsAppMessage.objects.filter(
            status='SENT',
            sent_at__lt=timeout,
            delivered_at__isnull=True
        )
        
        for message in stale_messages:
            try:
                message.mark_failed("Message delivery timed out")
                logger.warning(f"Marked stale message {message.message_id} as failed")
            except Exception as e:
                logger.error(f"Error cleaning up message {message.message_id}: {str(e)}")
                
    except Exception as e:
        logger.error(f"Error in WhatsApp cleanup task: {str(e)}")
        raise

@shared_task(bind=True)
def sync_message_status(self, message_id):
    """
    Sync message status with WhatsApp API.
    Used for manual status checks when webhook updates are missing.
    """
    try:
        whatsapp_service = WhatsAppService()
        message = WhatsAppMessage.objects.get(message_id=message_id)
        
        # Call WhatsApp API to get message status
        status = whatsapp_service.check_message_status(message_id)
        
        if status == 'delivered':
            message.mark_delivered()
        elif status == 'read':
            message.mark_read()
        elif status == 'failed':
            message.mark_failed("Failed according to status check")
            
        logger.info(f"Synced status for message {message_id}: {status}")
        
    except WhatsAppMessage.DoesNotExist:
        logger.error(f"Message {message_id} not found for status sync")
    except Exception as e:
        logger.error(f"Error syncing message status: {str(e)}")
        raise
