import logging
from django.core.cache import cache
from .models import WhatsAppMessage
from apps.chat.models import Conversation, Message
from .services import WhatsAppService

logger = logging.getLogger(__name__)

class WhatsAppConversationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_whatsapp_message(self, sender_phone: str, content: str, message_id: str) -> Message:
        """Process incoming WhatsApp message and integrate with chat system."""
        try:
            # Find or create conversation
            conversation = Conversation.objects.filter(
                client_phone=sender_phone,
                is_active=True
            ).first()

            if not conversation:
                conversation = Conversation.objects.create(
                    client_phone=sender_phone,
                    is_active=True
                )

            # Create message in chat system
            message = Message.objects.create(
                conversation=conversation,
                content=content,
                direction='IN'
            )

            # Create WhatsApp message record
            WhatsAppMessage.objects.create(
                phone_number=sender_phone,
                message_id=message_id,
                content=content,
                status='RECEIVED',
                conversation=conversation
            )

            return message

        except Exception as e:
            logger.error(f"Error processing WhatsApp message: {str(e)}")
            raise
