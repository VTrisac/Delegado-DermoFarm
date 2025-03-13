from django.db import models
from django.utils import timezone
from apps.chat.models import Conversation

class WhatsAppLog(models.Model):
    """Log of WhatsApp API interactions for monitoring and debugging."""
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    endpoint = models.CharField(max_length=255)
    request_payload = models.TextField()
    response_data = models.TextField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    status_code = models.IntegerField(null=True)

    class Meta:
        indexes = [
            models.Index(fields=['-created_at', 'endpoint']),
            models.Index(fields=['status_code', '-created_at'])
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.endpoint} - {self.created_at}"

class WhatsAppMessage(models.Model):
    """Track WhatsApp message delivery and status."""
    STATUS_CHOICES = [
        ('SENT', 'Sent'),
        ('DELIVERED', 'Delivered'),
        ('READ', 'Read'),
        ('FAILED', 'Failed'),
        ('RECEIVED', 'Received')
    ]

    phone_number = models.CharField(max_length=50, db_index=True)
    message_id = models.CharField(max_length=255, unique=True)
    content = models.TextField()
    media_url = models.URLField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='SENT')
    sent_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    conversation = models.ForeignKey(
        Conversation, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='whatsapp_messages'
    )

    class Meta:
        indexes = [
            models.Index(fields=['phone_number', '-sent_at']),
            models.Index(fields=['status', '-sent_at']),
            models.Index(fields=['conversation', '-sent_at']),
            models.Index(fields=['-delivered_at']),
            models.Index(fields=['-read_at'])
        ]
        ordering = ['-sent_at']

    def __str__(self):
        return f"{self.phone_number} - {self.sent_at}"

    def mark_delivered(self):
        """Mark message as delivered with timestamp."""
        self.status = 'DELIVERED'
        self.delivered_at = timezone.now()
        self.save(update_fields=['status', 'delivered_at'])

    def mark_read(self):
        """Mark message as read with timestamp."""
        self.status = 'READ'
        self.read_at = timezone.now()
        self.save(update_fields=['status', 'read_at'])

    def mark_failed(self, error_message):
        """Mark message as failed with error details."""
        self.status = 'FAILED'
        self.error_message = error_message
        self.save(update_fields=['status', 'error_message'])

    @property
    def delivery_status(self):
        """Get detailed delivery status information."""
        return {
            'status': self.status,
            'sent_at': self.sent_at,
            'delivered_at': self.delivered_at,
            'read_at': self.read_at,
            'error_message': self.error_message
        }