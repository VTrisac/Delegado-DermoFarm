from django.db import models
from apps.chat.models import Message

class WhatsAppMessage(models.Model):
    STATUS_CHOICES = [
        ('SENT', 'Enviado'),
        ('DELIVERED', 'Entregado'),
        ('READ', 'Leído'),
        ('FAILED', 'Fallido'),
    ]
    
    message = models.OneToOneField(Message, on_delete=models.CASCADE)
    whatsapp_message_id = models.CharField(max_length=100, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    sent_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'WhatsApp Message'
        verbose_name_plural = 'WhatsApp Messages'

    def __str__(self):
        return f"WhatsApp Message: {self.whatsapp_message_id}"
    
class WhatsAppLog(models.Model):
    message = models.ForeignKey('whatsapp.WhatsAppMessage', on_delete=models.CASCADE, related_name="logs")
    event_type = models.CharField(max_length=50)  # "RECEIVED", "PROCESSED", "SENT", "DELIVERED", "READ"
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} - {self.message.whatsapp_message_id}"