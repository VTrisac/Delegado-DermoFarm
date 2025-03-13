import json
import hmac
import hashlib
import logging
import requests
from functools import wraps
from time import sleep
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from requests.exceptions import RequestException
from .models import WhatsAppMessage, WhatsAppLog
from apps.chat.models import Message, Conversation

logger = logging.getLogger(__name__)

def retry_on_failure(max_retries=3, delay=1):
    """Decorator to retry API calls on failure with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        sleep_time = delay * (2 ** attempt)  # Exponential backoff
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}. "
                            f"Retrying in {sleep_time} seconds... Error: {str(e)}"
                        )
                        sleep(sleep_time)
            
            logger.error(
                f"All {max_retries} attempts failed for {func.__name__}. "
                f"Final error: {str(last_exception)}"
            )
            raise last_exception
        return wrapper
    return decorator

class WhatsAppService:
    """Service class for handling WhatsApp message interactions."""
    
    def __init__(self):
        self.api_url = settings.WHATSAPP_API_URL
        self.api_token = settings.WHATSAPP_API_TOKEN
        self.webhook_secret = settings.WHATSAPP_WEBHOOK_SECRET
        self.cache_timeout = 3600  # 1 hour
        
    def _get_headers(self):
        """Get headers for API requests with proper authentication."""
        return {
            'Authorization': f'Bearer {self.api_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
    
    def _log_api_interaction(self, endpoint, payload, response, error=None):
        """Log API interactions for debugging and monitoring."""
        try:
            WhatsAppLog.objects.create(
                endpoint=endpoint,
                request_payload=json.dumps(payload),
                response_data=json.dumps(response) if response else None,
                error_message=str(error) if error else None,
                status_code=response.status_code if response else None
            )
        except Exception as e:
            logger.error(f"Error logging WhatsApp API interaction: {str(e)}")
    
    @retry_on_failure(max_retries=3)
    def send_message(self, phone_number, content, conversation_id=None, media_url=None):
        """
        Send a WhatsApp message with retry mechanism and proper error handling.
        Supports both text and media messages.
        """
        endpoint = f"{self.api_url}/messages"
        
        # Normalize phone number
        phone_number = self._normalize_phone_number(phone_number)
        
        # Prepare message payload
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone_number,
            "type": "text" if not media_url else "media"
        }
        
        if media_url:
            payload["media"] = {
                "link": media_url,
                "caption": content
            }
        else:
            payload["text"] = {"body": content}
        
        try:
            response = requests.post(
                endpoint,
                headers=self._get_headers(),
                json=payload
            )
            response.raise_for_status()
            response_data = response.json()
            
            # Log the interaction
            self._log_api_interaction(endpoint, payload, response)
            
            # Extract message ID from the response
            message_id = response_data.get('messages', [{}])[0].get('id')
            
            # Create WhatsApp message record
            whatsapp_message = WhatsAppMessage.objects.create(
                phone_number=phone_number,
                content=content,
                media_url=media_url,
                message_id=message_id,
                status='SENT',
                conversation_id=conversation_id
            )
            
            # Add sid property to the WhatsAppMessage object to maintain compatibility with existing code
            whatsapp_message.sid = message_id
            
            return whatsapp_message
            
        except RequestException as e:
            self._log_api_interaction(endpoint, payload, None, error=e)
            raise
    
    def verify_webhook_signature(self, request):
        """Verify the authenticity of incoming webhook requests."""
        signature = request.headers.get('X-Hub-Signature-256', '')
        if not signature or not signature.startswith('sha256='):
            return False
            
        try:
            # Get the signature from the header
            received_signature = signature.split('sha256=')[1]
            
            # Calculate expected signature
            expected_signature = hmac.new(
                self.webhook_secret.encode('utf-8'),
                request.body,
                hashlib.sha256
            ).hexdigest()
            
            # Compare signatures using hmac.compare_digest to prevent timing attacks
            return hmac.compare_digest(received_signature, expected_signature)
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {str(e)}")
            return False
    
    def parse_webhook_data(self, data):
        """Parse and validate incoming webhook data."""
        try:
            processed_messages = []
            
            # Extract messages from the webhook payload
            entries = data.get('entry', [])
            for entry in entries:
                changes = entry.get('changes', [])
                for change in changes:
                    messages = change.get('value', {}).get('messages', [])
                    
                    for message in messages:
                        processed_message = self._process_webhook_message(message)
                        if processed_message:
                            processed_messages.append(processed_message)
            
            return processed_messages
            
        except Exception as e:
            logger.error(f"Error parsing webhook data: {str(e)}")
            return []
    
    def _process_webhook_message(self, message):
        """Process individual messages from webhook payload."""
        try:
            message_type = message.get('type')
            message_id = message.get('id')
            
            # Skip if we've already processed this message
            cache_key = f'whatsapp_msg_{message_id}'
            if cache.get(cache_key):
                return None
                
            # Mark message as processed
            cache.set(cache_key, True, self.cache_timeout)
            
            processed_message = {
                'id': message_id,
                'from': message.get('from'),
                'timestamp': message.get('timestamp'),
                'type': message_type,
            }
            
            if message_type == 'text':
                processed_message['content'] = message.get('text', {}).get('body', '')
            elif message_type in ['image', 'video', 'audio', 'document']:
                media = message.get(message_type, {})
                processed_message.update({
                    'content': f"[{message_type.title()}: {media.get('link', '')}]",
                    'mime_type': media.get('mime_type'),
                    'media_id': media.get('id')
                })
            elif message_type == 'location':
                location = message.get('location', {})
                processed_message['content'] = (
                    f"[Location: {location.get('latitude')}, {location.get('longitude')}]"
                )
            
            return processed_message
            
        except Exception as e:
            logger.error(f"Error processing webhook message: {str(e)}")
            return None
    
    def handle_incoming_message(self, sender_phone, message_content, message_sid):
        """Handle incoming WhatsApp messages and integrate with chat system."""
        try:
            # Find or create conversation
            conversation = Conversation.objects.filter(
                client_phone=sender_phone,
                is_active=True
            ).first()
            
            if not conversation:
                from apps.agents.models import AgentProfile
                agent = AgentProfile.objects.filter(is_active=True).first()
                
                if not agent:
                    logger.error("No active agents available")
                    return None, None
                
                conversation = Conversation.objects.create(
                    agent=agent,
                    client_phone=sender_phone,
                    is_active=True
                )
            
            # Create message record
            user_message = Message.objects.create(
                conversation=conversation,
                content=message_content,
                direction='IN',
                timestamp=timezone.now()
            )
            
            # Create WhatsApp message record
            WhatsAppMessage.objects.create(
                phone_number=sender_phone,
                content=message_content,
                message_id=message_sid,
                status='RECEIVED',
                conversation=conversation
            )
            
            return user_message, conversation
            
        except Exception as e:
            logger.error(f"Error handling incoming WhatsApp message: {str(e)}")
            raise
    
    @staticmethod
    def _normalize_phone_number(phone):
        """Normalize phone numbers to WhatsApp's expected format."""
        # Remove any non-digit characters
        phone = ''.join(filter(str.isdigit, phone))
        
        # Ensure it starts with country code
        if not phone.startswith('1') and not phone.startswith('52'):
            phone = '52' + phone
        
        return phone
