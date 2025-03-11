from celery import shared_task
import logging
import traceback
from apps.chat.models import Message
from apps.chat.services import ChatProcessor
from apps.chat.tasks import process_message  # Import the centralized task

logger = logging.getLogger(__name__)

def get_message_context(conversation):
    """Obtiene los últimos mensajes de la conversación y la información del agente para dar contexto a ChatGPT."""
    context = {}
    
    # Add delegate if available
    if conversation.delegate:
        context['delegate'] = {
            'name': conversation.delegate.name,
            'code': conversation.delegate.code
        }
    
    # Add conversation history
    recent_messages = Message.objects.filter(
        conversation=conversation
    ).order_by('-timestamp')[:5].values('content', 'direction')
    
    if recent_messages:
        context['history'] = list(reversed(list(recent_messages)))
    
    return context

@shared_task(bind=True, max_retries=3)
def handle_whatsapp_message(self, message_id):
    """
    Handle processing for WhatsApp messages.
    
    This task is a wrapper that adds WhatsApp-specific functionality
    before delegating to the unified process_message task.
    
    Args:
        message_id: ID of the message to process
    """
    try:
        logger.info(f"Handling WhatsApp message {message_id}")
        
        # Get message
        message = Message.objects.select_related('conversation').get(id=message_id)
        
        # Add any WhatsApp-specific preprocessing here if needed
        # For example: special handling for media messages, etc.
        
        # Then use the unified message processing task
        process_message.delay(message_id, source='whatsapp')
        
        return f"WhatsApp message {message_id} handed off to unified processing system"
        
    except Message.DoesNotExist:
        logger.error(f"Message {message_id} not found")
        raise self.retry(countdown=2 ** self.request.retries)
    except Exception as e:
        logger.error(f"Error handling WhatsApp message {message_id}: {str(e)}")
        logger.error(traceback.format_exc())
        raise self.retry(countdown=2 ** self.request.retries)
