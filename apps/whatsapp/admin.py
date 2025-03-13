from django.contrib import admin
from .models import WhatsAppMessage, WhatsAppLog

@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ('message_id', 'status', 'sent_at', 'delivered_at', 'read_at')
    search_fields = ('message_id', 'status', 'phone_number')
    list_filter = ('status', 'sent_at')

@admin.register(WhatsAppLog)
class WhatsAppLogAdmin(admin.ModelAdmin):
    list_display = ('endpoint', 'created_at', 'status_code')
    list_filter = ('endpoint', 'status_code')
    search_fields = ('endpoint', 'request_payload', 'response_data')