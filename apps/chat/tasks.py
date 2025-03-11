from celery import shared_task
import logging
import traceback
from .models import Message, Conversation
from .services import ChatProcessor

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_message(self, message_id: int, source: str = 'web'):
    """
    Unified message processing task for both web chat and WhatsApp.
    Process a message with SmartResponseEngine first, then fallback to ChatGPT if needed.
    Updates the placeholder message with the response.
    
    Args:
        message_id: ID of the message to process
        source: Source of the message ('web', 'whatsapp', 'api', etc.)
        
    Returns:
        str: Status message
    """
    try:
        logger.info(f"Processing message {message_id} from source: {source}")
        
        # Get the message
        message = Message.objects.select_related('conversation').get(id=message_id)
        logger.debug(f"Retrieved message: {message.content[:50]}...")
        
        # Find the placeholder message that we need to update
        placeholder = Message.objects.filter(
            conversation=message.conversation,
            direction='OUT',
            content="Procesando respuesta..."
        ).order_by('-timestamp').first()
        
        # Initialize the processor
        processor = ChatProcessor()
        
        try:
            # Generate a response using our unified processing pipeline
            # This will use SmartResponseEngine first, then Q&A system, then GPT if needed
            success, response = processor.process_message(message)
            
            if not success:
                error_msg = f"Failed to process message {message_id}: {response}"
                logger.error(error_msg)
                error_response = "Lo siento, ocurrió un error al procesar tu mensaje. Por favor, intenta de nuevo en unos momentos."
                
                if placeholder:
                    placeholder.content = error_response
                    placeholder.ai_processed = True
                    placeholder.save()
                else:
                    processor.create_response_message(
                        conversation=message.conversation,
                        content=error_response
                    )
                    
                raise Exception(error_msg)
            
            logger.info(f"Generated response ({len(response)} chars)")
            
            # Format response based on the source
            formatted_response = response
            if source == 'whatsapp':
                formatted_response = processor.prepare_message_for_whatsapp(response)
            
            # Update the placeholder or create a new response message
            response_message = None
            if placeholder:
                logger.info(f"Updating placeholder message {placeholder.id}")
                placeholder.content = formatted_response
                placeholder.ai_processed = True
                placeholder.save()
                response_message = placeholder
            else:
                logger.info("Creating new response message")
                response_message = processor.create_response_message(
                    conversation=message.conversation,
                    content=formatted_response
                )
            
            # For WhatsApp, send the message via WhatsApp API
            if source == 'whatsapp':
                logger.info("Message is from WhatsApp, sending response back via WhatsApp...")
                try:
                    # Import here to avoid circular imports
                    from apps.whatsapp.services import WhatsAppService
                    whatsapp_service = WhatsAppService()
                    
                    # Send the response back to WhatsApp
                    whatsapp_response = whatsapp_service.send_message(
                        phone_number=message.conversation.client_phone,
                        content=formatted_response,
                        conversation_id=message.conversation.id
                    )
                    
                    logger.info(f"WhatsApp response sent with SID: {whatsapp_response.sid}")
                except Exception as whatsapp_error:
                    logger.error(f"Failed to send message to WhatsApp: {str(whatsapp_error)}")
                    logger.error(traceback.format_exc())
                    # Don't raise here, we've already processed the message successfully
            
            # Update conversation metadata
            conversation = message.conversation
            conversation.updated_at = response_message.timestamp
            conversation.save(update_fields=['updated_at'])
            
            return f"Successfully processed message {message_id} from {source}"
            
        except Exception as e:
            # Make sure we don't leave the placeholder hanging
            if placeholder:
                logger.warning(f"Error occurred, updating placeholder with friendly error message: {str(e)}")
                placeholder.content = "Lo siento, no pude procesar tu mensaje en este momento. Por favor, intenta nuevamente."
                placeholder.ai_processed = True
                placeholder.save()
            raise
        
    except Message.DoesNotExist:
        logger.error(f"Message {message_id} not found")
        raise self.retry(countdown=2 ** self.request.retries)
        
    except Exception as e:
        logger.error(f"Error processing message {message_id}: {str(e)}")
        logger.error(traceback.format_exc())
        
        # Try one more time to update any placeholder with an error message
        try:
            message = Message.objects.select_related('conversation').get(id=message_id)
            placeholder = Message.objects.filter(
                conversation=message.conversation,
                direction='OUT',
                content="Procesando respuesta..."
            ).order_by('-timestamp').first()
            
            if placeholder:
                placeholder.content = "Lo siento, ocurrió un error al procesar tu mensaje. Por favor, intenta de nuevo."
                placeholder.ai_processed = True
                placeholder.save()
        except Exception as inner_error:
            logger.error(f"Failed to update placeholder with error message: {str(inner_error)}")
            
        raise self.retry(countdown=2 ** self.request.retries)