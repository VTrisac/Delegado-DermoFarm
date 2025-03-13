from celery import shared_task
from django.core.cache import cache
from django.utils import timezone
import logging
from .models import Message, Conversation
from .services import ChatGPTService, SmartResponseEngine

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_message(self, message_id: int):
    """Process a chat message and generate response."""
    try:
        # Get the message and conversation
        message = Message.objects.select_related('conversation').get(id=message_id)
        conversation = message.conversation
        
        # Check if this was a confirmed message
        cache_key = f'confirmed_msg_{message.id}'
        was_confirmed = cache.get(cache_key)
        if was_confirmed:
            cache.delete(cache_key)
            # Add context about confirmation to message
            message.context = {
                'was_confirmed': True,
                'confirmed_at': timezone.now().isoformat()
            }
            message.save(update_fields=['context'])
        
        # Initialize services
        smart_engine = SmartResponseEngine(conversation)
        chatgpt_service = ChatGPTService()
        
        # First try smart engine response
        response_text = smart_engine.process_message(message.content)
        
        # If smart engine couldn't handle it, use ChatGPT
        if not response_text or response_text == "__USE_GPT__":
            # Build context for GPT
            context = {
                'conversation_id': conversation.id,
                'message_history': _get_message_history(conversation),
                'was_confirmed': was_confirmed,
                'delegate': conversation.delegate.name if conversation.delegate else None
            }
            
            response_text = chatgpt_service.process_message(
                message.content,
                context=context
            )
        
        # Update placeholder message with response
        placeholder = Message.objects.filter(
            conversation=conversation,
            direction='OUT',
            ai_processed=False
        ).order_by('-timestamp').first()
        
        if placeholder:
            placeholder.content = response_text
            placeholder.ai_processed = True
            placeholder.processed_at = timezone.now()
            placeholder.save()
        else:
            # Create new response message if no placeholder exists
            Message.objects.create(
                conversation=conversation,
                content=response_text,
                direction='OUT',
                ai_processed=True,
                processed_at=timezone.now()
            )
        
        # Mark original message as processed
        message.ai_processed = True
        message.processed_at = timezone.now()
        message.save()
        
        # Update conversation last activity
        conversation.save()  # This updates updated_at
        
        return {
            'success': True,
            'message_id': message.id,
            'response_length': len(response_text)
        }
        
    except Message.DoesNotExist:
        logger.error(f"Message {message_id} not found")
        return {'success': False, 'error': 'Message not found'}
        
    except Exception as e:
        logger.error(f"Error processing message {message_id}: {str(e)}")
        # Retry with exponential backoff
        try:
            self.retry(exc=e, countdown=self.request.retries * 60)
        except self.MaxRetriesExceededError:
            # After max retries, update placeholder with error message
            try:
                placeholder = Message.objects.filter(
                    conversation_id=message.conversation_id,
                    direction='OUT',
                    ai_processed=False
                ).order_by('-timestamp').first()
                
                if placeholder:
                    placeholder.content = "Lo siento, ha ocurrido un error procesando tu mensaje. Por favor, intenta de nuevo."
                    placeholder.ai_processed = True
                    placeholder.save()
            except:
                pass
            
            return {
                'success': False,
                'error': f'Max retries exceeded: {str(e)}'
            }

def _get_message_history(conversation, limit=5):
    """Get recent message history for context."""
    messages = Message.objects.filter(
        conversation=conversation
    ).order_by('-timestamp')[:limit]
    
    return [{
        'content': msg.content,
        'direction': msg.direction,
        'timestamp': msg.timestamp.isoformat()
    } for msg in reversed(messages)]