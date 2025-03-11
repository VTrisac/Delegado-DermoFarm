from datetime import timezone, datetime
from celery import shared_task
# Eliminada la importación de Twilio
import requests
from django.conf import settings
from apps.chat.services import ChatProcessor
from apps.chat.models import Message, Conversation
from apps.whatsapp.models import WhatsAppMessage, WhatsAppLog
import logging
import re
import uuid
import json
import hmac
import hashlib

logger = logging.getLogger(__name__)

class WhatsAppService:
    """
    Service for handling all WhatsApp-related functionality:
    - Sending messages via WhatsApp API
    - Receiving messages from WhatsApp webhook
    - Tracking message status
    - Integrating with the unified chat system
    """
    
    def __init__(self):
        # Cargar configuraciones desde settings
        self.api_url = settings.WHATSAPP_API_URL
        self.api_token = settings.WHATSAPP_API_TOKEN
        self.webhook_secret = settings.WHATSAPP_WEBHOOK_SECRET
        self.whatsapp_phone_id = settings.WHATSAPP_PHONE_ID
        self.whatsapp_number = settings.WHATSAPP_PHONE_NUMBER
        
    def send_message(self, phone_number, content, conversation_id=None):
        """
        Send a message via WhatsApp using generic API.
        
        Args:
            phone_number: Recipient phone number
            content: Message content
            conversation_id: Optional conversation ID for tracking
            
        Returns:
            The message object from the API
        """
        # Clean up phone number
        clean_number = self._clean_phone_number(phone_number)
        
        # Format message for WhatsApp
        content = self._format_for_whatsapp(content)
        
        # Generate unique message ID for tracking
        message_id = str(uuid.uuid4())
            
        logger.info(f"Sending WhatsApp message to {clean_number}")
        
        try:
            # Preparar la solicitud para la API de WhatsApp
            headers = {
                'Authorization': f'Bearer {self.api_token}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'messaging_product': 'whatsapp',
                'recipient_type': 'individual',
                'to': clean_number,
                'type': 'text',
                'text': {
                    'preview_url': False,
                    'body': content
                }
            }
            
            # Enviar mensaje a través de la API
            response = requests.post(
                f"{self.api_url}/v1/messages",
                headers=headers,
                json=payload
            )
            
            # Verificar respuesta
            if response.status_code not in (200, 201):
                logger.error(f"Error sending WhatsApp message: {response.status_code}, {response.text}")
                raise Exception(f"WhatsApp API error: {response.status_code}, {response.text}")
            
            # Extraer ID del mensaje de la respuesta
            response_data = response.json()
            whatsapp_message_id = response_data.get('messages', [{}])[0].get('id', message_id)
            
            logger.info(f"WhatsApp message sent: {whatsapp_message_id}")
            
            # Track the message if we have a conversation ID
            if conversation_id:
                try:
                    conversation = Conversation.objects.get(id=conversation_id)
                    # Create a message record if one doesn't exist
                    message, created = Message.objects.get_or_create(
                        conversation=conversation,
                        content=content,
                        direction='OUT',
                        defaults={'ai_processed': True}
                    )
                    
                    # Create WhatsApp tracking record
                    whatsapp_message = WhatsAppMessage.objects.create(
                        message=message,
                        whatsapp_message_id=whatsapp_message_id,
                        status='SENT'
                    )
                    
                    # Log the message sending event
                    WhatsAppLog.objects.create(
                        message=whatsapp_message,
                        event_type='SENT',
                        description=f"Message sent to {clean_number}"
                    )
                    
                    logger.info(f"Created WhatsApp tracking record: {whatsapp_message.id}")
                except Exception as db_error:
                    logger.error(f"Error tracking WhatsApp message in database: {str(db_error)}")
            
            # Crear un objeto similar a la respuesta de Twilio para mantener compatibilidad
            class ApiResponse:
                def __init__(self, sid):
                    self.sid = sid
                    
            return ApiResponse(whatsapp_message_id)
        except Exception as e:
            logger.error(f"Error sending WhatsApp message: {str(e)}")
            raise
    
    def verify_webhook_signature(self, request):
        """
        Verifica la firma del webhook para asegurar que la solicitud es legítima
        
        Args:
            request: Django request object
            
        Returns:
            bool: True si la firma es válida
        """
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured, skipping signature verification")
            return True
            
        try:
            # Obtener la firma del encabezado
            signature = request.headers.get('X-Hub-Signature-256', '')
            if not signature.startswith('sha256='):
                logger.warning("Invalid signature format")
                return False
                
            signature = signature[7:]  # Quita 'sha256='
            
            # Calcular el HMAC usando el cuerpo de la solicitud y el secreto
            body = request.body
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                body,
                hashlib.sha256
            ).hexdigest()
            
            # Comparar firmas (constante-time para evitar timing attacks)
            return hmac.compare_digest(signature, expected_signature)
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {str(e)}")
            return False
    
    def handle_incoming_message(self, sender_phone, message_content, message_sid):
        """
        Handle an incoming WhatsApp message by creating/retrieving conversation
        and using the chat processor to process it.
        
        Args:
            sender_phone: Sender's phone number
            message_content: Message content
            message_sid: Message ID for tracking
            
        Returns:
            tuple: (user_message, conversation)
        """
        from apps.agents.models import AgentProfile
        
        # Clean up phone number
        clean_number = self._clean_phone_number(sender_phone)
        
        # Find or create conversation for this client
        conversation = Conversation.objects.filter(client_phone=clean_number, is_active=True).first()
        
        if not conversation:
            # Get available agent
            agent = AgentProfile.objects.filter(is_active=True).first()
            if not agent:
                logger.error("No active agent found for new WhatsApp conversation")
                raise ValueError("No active agents available to handle this conversation")
            
            # Create new conversation
            conversation = Conversation.objects.create(
                agent=agent,
                client_phone=clean_number,
                is_active=True,
                thread_id=message_sid  # Use message_sid as thread_id for tracking
            )
            logger.info(f"Created new conversation {conversation.id} for {clean_number}")
        
        # Use the chat processor to handle the incoming message
        chat_processor = ChatProcessor()
        user_message, placeholder = chat_processor.handle_incoming_message(
            message_content,
            conversation,
            source='whatsapp'
        )
        
        # Create WhatsApp tracking record
        whatsapp_message = WhatsAppMessage.objects.create(
            message=user_message,
            whatsapp_message_id=message_sid,
            status='RECEIVED'
        )
        
        # Log the received message
        WhatsAppLog.objects.create(
            message=whatsapp_message,
            event_type='RECEIVED',
            description=f"Message received from {clean_number}"
        )
        
        # Process the message using our unified task system
        from apps.chat.tasks import process_message
        process_message.delay(user_message.id, source='whatsapp')
        
        return user_message, conversation
    
    def parse_webhook_data(self, data):
        """
        Parsea los datos del webhook de WhatsApp
        
        Args:
            data: Datos JSON del webhook
            
        Returns:
            list: Lista de mensajes procesados
        """
        processed_messages = []
        
        try:
            # Verificar si hay cambios en la mensajería
            if 'entry' not in data:
                return processed_messages
                
            for entry in data['entry']:
                if 'changes' not in entry:
                    continue
                    
                for change in entry['changes']:
                    if change.get('field') != 'messages':
                        continue
                        
                    value = change.get('value', {})
                    
                    if 'messages' not in value:
                        # Esto podría ser una actualización de estado
                        self._process_status_update(value)
                        continue
                    
                    messages = value.get('messages', [])
                    for msg in messages:
                        msg_type = msg.get('type')
                        msg_from = value.get('contacts', [{}])[0].get('wa_id') if value.get('contacts') else None
                        
                        if not msg_from:
                            logger.warning(f"Missing sender in WhatsApp webhook message: {msg}")
                            continue
                        
                        msg_id = msg.get('id', '')
                        timestamp = msg.get('timestamp', '')
                        
                        # Procesar según el tipo de mensaje
                        if msg_type == 'text':
                            text = msg.get('text', {}).get('body', '')
                            processed_messages.append({
                                'type': 'TEXT',
                                'from': msg_from,
                                'id': msg_id,
                                'timestamp': timestamp,
                                'content': text
                            })
                        elif msg_type == 'image':
                            media = msg.get('image', {})
                            url = self._get_media_url(media.get('id')) if media.get('id') else None
                            caption = media.get('caption', '')
                            
                            content = caption if caption else "[Image]"
                            if url:
                                content += f"\n[Image: {url}]"
                                
                            processed_messages.append({
                                'type': 'MEDIA',
                                'from': msg_from,
                                'id': msg_id,
                                'timestamp': timestamp,
                                'content': content,
                                'media_type': 'image',
                                'media_url': url
                            })
                        elif msg_type in ('audio', 'video', 'document'):
                            media = msg.get(msg_type, {})
                            url = self._get_media_url(media.get('id')) if media.get('id') else None
                            caption = media.get('caption', '') if msg_type != 'audio' else ''
                            
                            content = caption if caption else f"[{msg_type.capitalize()}]"
                            if url:
                                content += f"\n[{msg_type.capitalize()}: {url}]"
                                
                            processed_messages.append({
                                'type': 'MEDIA',
                                'from': msg_from,
                                'id': msg_id,
                                'timestamp': timestamp,
                                'content': content,
                                'media_type': msg_type,
                                'media_url': url
                            })
                        elif msg_type == 'location':
                            location = msg.get('location', {})
                            lat = location.get('latitude')
                            lng = location.get('longitude')
                            name = location.get('name', '')
                            address = location.get('address', '')
                            
                            content = f"Location: {lat}, {lng}"
                            if name:
                                content += f"\nName: {name}"
                            if address:
                                content += f"\nAddress: {address}"
                                
                            processed_messages.append({
                                'type': 'LOCATION',
                                'from': msg_from,
                                'id': msg_id,
                                'timestamp': timestamp,
                                'content': content,
                                'latitude': lat,
                                'longitude': lng
                            })
                            
        except Exception as e:
            logger.error(f"Error parsing webhook data: {str(e)}")
            
        return processed_messages
    
    def _get_media_url(self, media_id):
        """
        Obtiene la URL de un archivo multimedia de WhatsApp
        
        Args:
            media_id: ID del archivo multimedia
            
        Returns:
            str: URL del archivo multimedia
        """
        try:
            headers = {
                'Authorization': f'Bearer {self.api_token}'
            }
            
            response = requests.get(
                f"{self.api_url}/{media_id}",
                headers=headers
            )
            
            if response.status_code != 200:
                logger.error(f"Error getting media URL: {response.status_code}, {response.text}")
                return None
                
            data = response.json()
            return data.get('url')
        except Exception as e:
            logger.error(f"Error retrieving media URL: {str(e)}")
            return None
    
    def _process_status_update(self, value):
        """
        Procesa actualizaciones de estado de mensajes
        
        Args:
            value: Datos del cambio de estado
        """
        try:
            statuses = value.get('statuses', [])
            for status in statuses:
                msg_id = status.get('id')
                status_type = status.get('status')
                
                if not msg_id or not status_type:
                    continue
                    
                # Mapear estados a nuestros estados internos
                status_map = {
                    'sent': 'SENT',
                    'delivered': 'DELIVERED',
                    'read': 'READ',
                    'failed': 'FAILED'
                }
                
                internal_status = status_map.get(status_type.lower())
                if internal_status:
                    self.update_message_status(msg_id, internal_status)
        except Exception as e:
            logger.error(f"Error processing status update: {str(e)}")
    
    def _clean_phone_number(self, phone_number):
        """Clean up a phone number by removing formatting and prefixes"""
        # Remove whatsapp: prefix if present
        if phone_number.startswith('whatsapp:'):
            phone_number = phone_number[9:]
            
        # Remove any non-digit characters except +
        phone_number = re.sub(r'[^\d+]', '', phone_number)
        
        # Ensure number starts with + if it's an international number
        if not phone_number.startswith('+'):
            if phone_number.startswith('00'):
                phone_number = '+' + phone_number[2:]
            elif len(phone_number) > 10:  # Assume it's international but missing +
                phone_number = '+' + phone_number
                
        return phone_number
    
    def _format_for_whatsapp(self, content):
        """Format message content appropriately for WhatsApp"""
        # Limit length
        if len(content) > 4000:
            content = content[:3997] + "..."
        
        # Replace multiple newlines with just two
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # Convert markdown style formatting to WhatsApp formatting
        # WhatsApp uses *bold*, _italic_, and ~strikethrough~
        content = re.sub(r'\*\*(.*?)\*\*', r'*\1*', content)  # Convert **bold** to *bold*
        content = re.sub(r'__(.*?)__', r'_\1_', content)      # Convert __italic__ to _italic_
        
        return content
        
    def update_message_status(self, whatsapp_message_id, status):
        """
        Update the status of a WhatsApp message
        
        Args:
            whatsapp_message_id: The WhatsApp Message ID
            status: The new status ('DELIVERED', 'READ', 'FAILED')
            
        Returns:
            bool: Success status
        """
        try:
            whatsapp_message = WhatsAppMessage.objects.get(whatsapp_message_id=whatsapp_message_id)
            whatsapp_message.status = status
            
            if status == 'DELIVERED':
                whatsapp_message.delivered_at = timezone.now()
            elif status == 'READ':
                whatsapp_message.read_at = timezone.now()
                
            whatsapp_message.save()
            
            # Log status update
            WhatsAppLog.objects.create(
                message=whatsapp_message,
                event_type=f'STATUS_{status}',
                description=f"Message status updated to {status}"
            )
            
            return True
            
        except WhatsAppMessage.DoesNotExist:
            logger.error(f"WhatsApp message with ID {whatsapp_message_id} not found")
            return False
        except Exception as e:
            logger.error(f"Error updating WhatsApp message status: {str(e)}")
            return False

# This is now superseded by the unified process_message task in apps.chat.tasks
# Kept for backwards compatibility, but redirects to the unified system
@shared_task
def process_incoming_message(message_id):
    """Legacy task - use apps.chat.tasks.process_message instead"""
    from apps.chat.tasks import process_message
    logger.warning("Using deprecated process_incoming_message task, use apps.chat.tasks.process_message instead")
    process_message.delay(message_id, source='whatsapp_legacy')
