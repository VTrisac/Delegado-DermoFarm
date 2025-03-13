from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.cache import cache
import json
import logging
from .models import Message, Conversation
from .services import ChatGPTService, ChatProcessor, SmartResponseEngine
from .tasks import process_message

logger = logging.getLogger(__name__)

@require_http_methods(["GET"])
def chat_view(request):
    """Main chat interface view."""
    conversation_id = request.GET.get('conversation_id')
    
    try:
        conversation = Conversation.objects.get(id=conversation_id) if conversation_id else None
        
        if conversation:
            chat_messages = Message.objects.filter(
                conversation=conversation,
                direction__in=['IN', 'OUT']
            ).order_by('timestamp')[:50]
        else:
            chat_messages = []
            
        return render(request, 'chat/chat.html', {
            'current_conversation_id': conversation_id,
            'chat_messages': chat_messages,
        })
        
    except Conversation.DoesNotExist:
        return JsonResponse({'error': 'Conversation not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in chat_view: {str(e)}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@require_http_methods(["POST"])
def send_message(request):
    """Handle sending chat messages with confirmation support."""
    try:
        data = json.loads(request.body)
        message_content = data.get('content', '').strip()
        conversation_id = data.get('conversation_id')
        
        if not message_content:
            return JsonResponse({'error': 'Message content is required'}, status=400)
            
        # Get or create conversation
        conversation = None
        if conversation_id:
            conversation = Conversation.objects.get(id=conversation_id)
        else:
            conversation = Conversation.objects.create(
                client_phone=request.session.get('phone_number'),
                is_active=True
            )
            
        # Check if this message requires confirmation
        requires_confirmation = _check_confirmation_required(message_content)
        
        if requires_confirmation:
            # Store pending message in cache
            cache_key = f'pending_msg_{conversation.id}'
            cache.set(cache_key, message_content, timeout=300)  # 5 minutes
            
            return JsonResponse({
                'requires_confirmation': True,
                'confirmation_message': '¿Desea continuar con la iteración?'
            })
            
        # Process message directly if no confirmation needed
        return _process_chat_message(message_content, conversation)
        
    except Conversation.DoesNotExist:
        return JsonResponse({'error': 'Conversation not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in send_message: {str(e)}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

@require_http_methods(["POST"])
def confirm_message(request):
    """Handle message confirmation response."""
    try:
        data = json.loads(request.body)
        conversation_id = data.get('conversation_id')
        confirmed = data.get('confirmed', False)
        
        if not conversation_id:
            return JsonResponse({'error': 'Conversation ID required'}, status=400)
            
        # Get pending message from cache
        cache_key = f'pending_msg_{conversation_id}'
        message_content = cache.get(cache_key)
        
        if not message_content:
            return JsonResponse({'error': 'No pending message found'}, status=400)
            
        # Clear the pending message
        cache.delete(cache_key)
        
        if not confirmed:
            return JsonResponse({'status': 'cancelled'})
            
        # Process the confirmed message
        conversation = Conversation.objects.get(id=conversation_id)
        return _process_chat_message(message_content, conversation)
        
    except Conversation.DoesNotExist:
        return JsonResponse({'error': 'Conversation not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in confirm_message: {str(e)}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

def _check_confirmation_required(message_content):
    """Check if message needs confirmation based on content."""
    confirmation_triggers = [
        'continuar',
        'siguiente',
        'proceder',
        'avanzar',
        'confirmar'
    ]
    
    return any(trigger in message_content.lower() for trigger in confirmation_triggers)

def _process_chat_message(message_content, conversation):
    """Process chat message and return response."""
    try:
        # Create user message
        user_message = Message.objects.create(
            conversation=conversation,
            content=message_content,
            direction='IN'
        )
        
        # Create placeholder for response
        placeholder = Message.objects.create(
            conversation=conversation,
            content="Procesando respuesta...",
            direction='OUT'
        )
        
        # Initialize chat processor
        chat_processor = ChatProcessor(conversation)
        
        # Process outgoing message if it's a WhatsApp conversation
        if conversation.client_phone and conversation.client_phone.startswith('+'):
            if not chat_processor.process_outgoing_message(placeholder):
                logger.error(f"Failed to send message to WhatsApp for conversation {conversation.id}")
        
        # Queue message for processing
        process_message.delay(user_message.id)
        
        return JsonResponse({
            'status': 'queued',
            'message_id': user_message.id,
            'placeholder_id': placeholder.id
        })
        
    except Exception as e:
        logger.error(f"Error processing chat message: {str(e)}")
        raise

@require_http_methods(["GET"])
def get_messages(request):
    """Get messages for a conversation, supporting pagination."""
    conversation_id = request.GET.get('conversation_id')
    last_id = request.GET.get('last_id')
    limit = int(request.GET.get('limit', 50))
    
    try:
        # Validate conversation_id is a valid integer
        if not conversation_id or conversation_id == 'None':
            return JsonResponse({'messages': [], 'has_more': False})
            
        # Convert to integer to catch invalid IDs
        try:
            conversation_id = int(conversation_id)
        except ValueError:
            return JsonResponse({'error': 'Invalid conversation ID'}, status=400)
            
        conversation = Conversation.objects.get(id=conversation_id)
        
        # Build query for messages
        messages_query = Message.objects.filter(conversation=conversation)
        if last_id and last_id.isdigit():
            messages_query = messages_query.filter(id__gt=int(last_id))
            
        # Get messages with limit
        messages = messages_query.order_by('timestamp')[:limit]
        
        # Format messages for response
        message_data = [{
            'id': msg.id,
            'content': msg.content,
            'direction': msg.direction,
            'timestamp': msg.timestamp.isoformat(),
            'ai_processed': msg.ai_processed
        } for msg in messages]
        
        return JsonResponse({
            'messages': message_data,
            'has_more': len(message_data) == limit
        })
        
    except Conversation.DoesNotExist:
        return JsonResponse({'error': 'Conversation not found'}, status=404)
    except Exception as e:
        logger.error(f"Error getting messages: {str(e)}")
        return JsonResponse({'error': 'Internal server error'}, status=500)

# ... rest of the existing views stay the same ...