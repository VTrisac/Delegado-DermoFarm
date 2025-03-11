from django.urls import path
from apps.whatsapp import views

urlpatterns = [
    path('webhook/', views.webhook_handler, name='whatsapp-webhook'),
    path('conversations/', views.whatsapp_conversations, name='whatsapp-conversations'),
    path('status/', views.whatsapp_status, name='whatsapp-status'),
    path('message/<int:message_id>/approve/', views.approve_message, name='whatsapp-approve-message'),
    path('conversation/<int:conversation_id>/history/', views.message_history, name='whatsapp-message-history'),
    path('send-message/', views.send_direct_message, name='whatsapp-send-direct-message'),
]