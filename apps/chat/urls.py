from django.urls import path
from django.views.decorators.cache import cache_page
from . import views

urlpatterns = [
    # Chat interface endpoints
    path('', views.chat_view, name='chat'),
    path('send-message/', views.send_message, name='send-message'),
    path('confirm-message/', views.confirm_message, name='confirm-message'),
    
    # Message retrieval with short cache
    path('messages/', 
         cache_page(15)(views.get_messages),  # Cache messages for 15 seconds
         name='get-messages'),

    # Other existing endpoints...
]
