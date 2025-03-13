import requests
from rest_framework.permissions import IsAuthenticated
from oauth2_provider.contrib.rest_framework import TokenHasScope
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from apps.chat.models import Message, Conversation
from apps.whatsapp.models import WhatsAppMessage, WhatsAppLog
from apps.whatsapp.services import WhatsAppService
from apps.whatsapp.tasks import handle_whatsapp_message
import json
import logging
import traceback

logger = logging.getLogger(__name__)

@api_view(["POST"])
@permission_classes([IsAuthenticated, TokenHasScope])
def approve_message(request, message_id):
    """
    Endpoint to manually approve a message before sending via WhatsApp
    """
    try:
        message = Message.objects.get(id=message_id)
        
        if message.direction != 'OUT':
            return Response({"error": "Can only approve outgoing messages"}, status=400)
        
        whatsapp_service = WhatsAppService()
        response = whatsapp_service.send_message(
            phone_number=message.conversation.client_phone,
            content=message.content,
            conversation_id=message.conversation.id
        )
        
        return Response({"success": True, "message_id": response.sid})
    except Message.DoesNotExist:
        return Response({"error": "Message not found"}, status=404)
    except Exception as e:
        logger.error(f"Error approving WhatsApp message: {str(e)}")
        return Response({"error": str(e)}, status=500)

@csrf_exempt
def webhook_handler(request):
    """
    Handle incoming WhatsApp messages through webhook with improved efficiency.
    """
    whatsapp_service = WhatsAppService()
    
    # Handle GET request for webhook verification
    if request.method == "GET":
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        
        verify_token = getattr(settings, 'WHATSAPP_WEBHOOK_VERIFY_TOKEN', '')
        
        if mode == 'subscribe' and token == verify_token:
            logger.info("Webhook verified successfully")
            return HttpResponse(challenge, status=200)
        
        logger.warning(f"Failed webhook verification: mode={mode}")
        return HttpResponse("Verification Failed", status=403)
    
    # Handle POST request with incoming messages
    if request.method == "POST":
        try:
            # Rate limiting check using cache
            client_ip = request.META.get('REMOTE_ADDR')
            rate_key = f'whatsapp_rate_{client_ip}'
            request_count = cache.get(rate_key, 0)
            
            if request_count >= 100:  # Max 100 requests per minute
                logger.warning(f"Rate limit exceeded for {client_ip}")
                return HttpResponse("Rate limit exceeded", status=429)
            
            cache.set(rate_key, request_count + 1, timeout=60)
            
            # Verify webhook signature
            if not whatsapp_service.verify_webhook_signature(request):
                logger.warning("Invalid webhook signature")
                return HttpResponse("Invalid signature", status=403)
            
            # Parse webhook data
            try:
                body = request.body.decode('utf-8')
                data = json.loads(body)
                logger.debug(f"Received webhook data: {json.dumps(data)[:500]}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in webhook: {str(e)}")
                return HttpResponse("Invalid JSON", status=400)
            
            # Process messages in batches
            messages = whatsapp_service.parse_webhook_data(data)
            if not messages:
                return HttpResponse("No messages to process", status=200)
            
            # Group messages by conversation for bulk processing
            conversation_messages = {}
            for msg in messages:
                sender = msg['from']
                if sender not in conversation_messages:
                    conversation_messages[sender] = []
                conversation_messages[sender].append(msg)
            
            # Process each conversation's messages in bulk
            for sender, msgs in conversation_messages.items():
                try:
                    # Find or create conversation once per sender
                    conversation = Conversation.objects.filter(
                        client_phone=sender,
                        is_active=True
                    ).first()
                    
                    if not conversation:
                        from apps.agents.models import AgentProfile
                        agent = AgentProfile.objects.filter(is_active=True).first()
                        if not agent:
                            logger.error("No active agents available")
                            continue
                        
                        conversation = Conversation.objects.create(
                            agent=agent,
                            client_phone=sender,
                            is_active=True
                        )
                    
                    # Process messages for this conversation
                    for msg in msgs:
                        handle_whatsapp_message.delay({
                            'id': msg['id'],
                            'from': sender,
                            'content': msg['content'],
                            'conversation_id': conversation.id
                        })
                        
                except Exception as e:
                    logger.error(f"Error processing messages for {sender}: {str(e)}")
                    continue
            
            return HttpResponse("Messages queued for processing", status=200)
            
        except Exception as e:
            logger.error(f"Error in webhook handler: {str(e)}")
            logger.error(traceback.format_exc())
            # Always return 200 to prevent retries from WhatsApp
            return HttpResponse("Error processing webhook", status=200)
    
    return HttpResponse("Method not allowed", status=405)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def whatsapp_conversations(request):
    """Get all WhatsApp conversations"""
    # Identify WhatsApp conversations (those with phone numbers starting with +)
    conversations = Conversation.objects.filter(
        client_phone__startswith='+',
        is_active=True
    ).order_by('-updated_at')
    
    data = []
    for conv in conversations:
        last_message = Message.objects.filter(conversation=conv).order_by('-timestamp').first()
        last_message_text = None
        if last_message:
            # Truncate message content for display
            last_message_text = last_message.content[:50]
            if len(last_message.content) > 50:
                last_message_text += "..."
                
        data.append({
            'id': conv.id,
            'client_phone': conv.client_phone,
            'created_at': conv.created_at,
            'updated_at': conv.updated_at,
            'message_count': Message.objects.filter(conversation=conv).count(),
            'last_message': last_message_text,
            'last_message_time': last_message.timestamp if last_message else None
        })
    
    return Response(data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def whatsapp_status(request):
    """Get WhatsApp service status"""
    # Count of messages sent via WhatsApp
    sent_count = WhatsAppMessage.objects.filter(status='SENT').count()
    delivered_count = WhatsAppMessage.objects.filter(status='DELIVERED').count()
    read_count = WhatsAppMessage.objects.filter(status='READ').count()
    failed_count = WhatsAppMessage.objects.filter(status='FAILED').count()
    
    # Last day statistics
    one_day_ago = timezone.now() - timezone.timedelta(days=1)
    last_day_sent = WhatsAppMessage.objects.filter(sent_at__gte=one_day_ago).count()
    last_day_received = WhatsAppMessage.objects.filter(
        status='RECEIVED',
        message__timestamp__gte=one_day_ago
    ).count()
    
    # Check connection to the WhatsApp API
    whatsapp_service = WhatsAppService()
    whatsapp_status = "Connected"
    
    try:
        # Intenta una llamada simple a la API para verificar la conexión
        headers = {'Authorization': f'Bearer {whatsapp_service.api_token}'}
        response = requests.get(f"{whatsapp_service.api_url}/business_profiles", headers=headers)
        
        if response.status_code != 200:
            whatsapp_status = f"Error: API returned status {response.status_code}"
    except Exception as e:
        whatsapp_status = f"Error: {str(e)}"
    
    return Response({
        "status": "operational" if whatsapp_status == "Connected" else "error",
        "api_connection": whatsapp_status,
        "total_messages": {
            "sent": sent_count,
            "delivered": delivered_count,
            "read": read_count,
            "failed": failed_count
        },
        "last_24h": {
            "sent": last_day_sent,
            "received": last_day_received
        }
    })

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def message_history(request, conversation_id):
    """Get the message history for a specific WhatsApp conversation"""
    try:
        # Verify the conversation exists and is a WhatsApp conversation
        conversation = Conversation.objects.get(
            id=conversation_id, 
            client_phone__startswith='+',  # WhatsApp indicator
            is_active=True
        )
        
        # Get all messages for this conversation
        messages = Message.objects.filter(conversation=conversation).order_by('timestamp')
        
        # Format messages with delivery status where available
        message_data = []
        for msg in messages:
            # Extract media information if present in the message content
            media_info = None
            if msg.direction == 'IN' and '[Media:' in msg.content:
                # Simple extraction of media URLs
                import re
                media_urls = re.findall(r'\[(Image|Video|Audio|Document): (https?://[^\]]+)\]', msg.content)
                if media_urls:
                    media_info = [{'type': m_type, 'url': m_url} for m_type, m_url in media_urls]
            
            data = {
                'id': msg.id,
                'content': msg.content,
                'direction': msg.direction,
                'timestamp': msg.timestamp,
                'delivery_status': None,
                'media_info': media_info
            }
            
            # Add WhatsApp delivery info if available
            try:
                if msg.direction == 'OUT':  # Only outgoing messages have delivery status
                    whatsapp_msg = WhatsAppMessage.objects.get(message=msg)
                    data['delivery_status'] = {
                        'status': whatsapp_msg.status,
                        'delivered_at': whatsapp_msg.delivered_at,
                        'read_at': whatsapp_msg.read_at
                    }
            except WhatsAppMessage.DoesNotExist:
                pass
                
            message_data.append(data)
        
        return Response({
            'conversation': {
                'id': conversation.id,
                'client_phone': conversation.client_phone,
                'created_at': conversation.created_at,
                'total_messages': len(message_data)
            },
            'messages': message_data
        })
        
    except Conversation.DoesNotExist:
        return Response({"error": "Conversation not found or not a WhatsApp conversation"}, status=404)
    except Exception as e:
        logger.error(f"Error retrieving WhatsApp message history: {str(e)}")
        return Response({"error": str(e)}, status=500)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_direct_message(request):
    """
    Send a direct WhatsApp message to a specific phone number.
    This can be used outside of existing conversations.
    """
    try:
        phone_number = request.data.get('phone_number')
        message = request.data.get('message')
        
        if not phone_number or not message:
            return Response({
                "error": "Both phone_number and message are required"
            }, status=400)
        
        # Initialize WhatsApp service
        whatsapp_service = WhatsAppService()
        
        # Send the message
        response = whatsapp_service.send_message(
            phone_number=phone_number,
            content=message
        )
        
        return Response({
            "success": True,
            "message_id": response.sid,
            "status": "sent"
        })
        
    except Exception as e:
        logger.error(f"Error sending direct WhatsApp message: {str(e)}")
        return Response({"error": str(e)}, status=500)
