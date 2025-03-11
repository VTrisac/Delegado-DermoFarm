from django.contrib import admin
from .models import WhatsAppMessage

@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ('whatsapp_message_id', 'status', 'sent_at', 'delivered_at', 'read_at')
    search_fields = ('whatsapp_message_id', 'status')
    list_filter = ('status', 'sent_at')