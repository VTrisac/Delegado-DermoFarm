from rest_framework.permissions import IsAuthenticated
from oauth2_provider.contrib.rest_framework import TokenHasScope
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from apps.chat.models import Message, Conversation
from apps.whatsapp.models import WhatsAppMessage, WhatsAppLog
from apps.whatsapp.services import WhatsAppService
from apps.whatsapp.tasks import handle_whatsapp_message
from django.utils import timezone
from django.conf import settings
import json
import logging
import traceback
import requests
from urllib.parse import urlparse

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
    Handle incoming WhatsApp messages through webhook.
    This is the main entry point for messages from WhatsApp into our unified chat system.
    
    Supports multiple message types:
    - Text messages
    - Media messages (images, audio, video, documents)
    - Location messages
    - Status updates (delivered, read, failed)
    - Verification requests from the WhatsApp API
    """
    # Initialize WhatsApp service
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
        
        logger.warning(f"Failed webhook verification: mode={mode}, token={token}")
        return HttpResponse("Verification Failed", status=403)
    
    # Handle POST request with incoming messages or status updates
    if request.method == "POST":
        try:
            # Verificar firma del webhook para seguridad
            if not whatsapp_service.verify_webhook_signature(request):
                logger.warning("Invalid webhook signature")
                return HttpResponse("Invalid signature", status=403)
            
            # Parse the incoming webhook data
            try:
                body = request.body.decode('utf-8')
                data = json.loads(body)
                logger.info(f"Received WhatsApp webhook: {json.dumps(data)[:500]}")
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in webhook: {str(e)}")
                return HttpResponse("Invalid JSON", status=400)
            
            # Procesar los mensajes recibidos
            processed_messages = whatsapp_service.parse_webhook_data(data)
            
            # Si no hay mensajes, podría ser una actualización de estado o un evento que no necesita respuesta
            if not processed_messages:
                return HttpResponse("No messages to process", status=200)
                
            # Procesar cada mensaje
            for msg in processed_messages:
                try:
                    # Manejar el mensaje entrante según su tipo
                    sender_phone = msg['from']
                    message_content = msg['content']
                    message_id = msg['id']
                    
                    # Procesar el mensaje a través de nuestro sistema
                    user_message, conversation = whatsapp_service.handle_incoming_message(
                        sender_phone=sender_phone,
                        message_content=message_content,
                        message_sid=message_id
                    )
                    
                    logger.info(f"Successfully processed WhatsApp message from {sender_phone} into conversation {conversation.id}")
                    
                except Exception as msg_error:
                    logger.error(f"Error processing individual WhatsApp message: {str(msg_error)}")
                    logger.error(traceback.format_exc())
                    # Continuamos con el siguiente mensaje
                    
            # Retornar éxito
            return HttpResponse("Message(s) processed", status=200)
            
        except Exception as e:
            logger.error(f"Error in WhatsApp webhook handler: {str(e)}")
            logger.error(traceback.format_exc())
            return HttpResponse("Internal server error", status=200)  # Siempre retornar 200 para evitar reintentos

    # Método no admitido
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
