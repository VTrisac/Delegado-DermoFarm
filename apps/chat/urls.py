from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from .views import (
    ChatGPTView, 
    chat_view, 
    send_message, 
    conversation_detail, 
    send_chat_message, 
    get_latest_response, 
    get_conversation_messages, 
    login_view,
    terms_view,
    QuestionViewSet
)

router = DefaultRouter()
router.register(r'conversations', views.ConversationViewSet)
router.register(r'questions', views.QuestionViewSet)

urlpatterns = [
    path('login/', login_view, name="login"),
    path('terms/', terms_view, name="terms"),
    path('', chat_view, name="chat"),
    path('send/', send_message, name="chat-send-message"),
    path('api/', include(router.urls)),
    path('send-message/', send_chat_message, name='api-chat-send'),
    path('latest-response/', get_latest_response, name='api-latest-response'),
    path('messages/', get_conversation_messages, name='api-conversation-messages'),  # Nueva URL para obtener mensajes
    path('gpt/', ChatGPTView.as_view(), name='chat-gpt'),
    path('<int:conversation_id>/', conversation_detail, name="conversation-detail"),
    
    # Pharmacy endpoints
    path('api/pharmacies/search/', views.search_pharmacies, name='search_pharmacies'),
    
    # Visit and feedback endpoints
    path('api/visits/<int:visit_id>/summary/', views.get_visit_summary, name='get_visit_summary'),
    path('api/visits/<int:visit_id>/confirm/', views.confirm_visit_summary, name='confirm_visit_summary'),
    path('api/visits/<int:visit_id>/report/', views.generate_visit_report, name='generate_visit_report'),
    path('api/visits/feedback/', views.submit_visit_feedback, name='submit_visit_feedback'),
    path('visits/<int:visit_id>/', views.visit_summary_view, name='visit-summary'),
    
    # Q&A API endpoints
    path('api/qa/query/', views.query_qa, name='query_qa'),
    path('api/qa/stats/', views.get_qa_statistics, name='qa_stats'),
    path('api/qa/feedback/<int:interaction_id>/', views.provide_feedback, name='qa_feedback'),
    
    # Nuevo endpoint para depuración
    path('debug/response/<int:conversation_id>/', views.debug_latest_response, name='debug_latest_response'),
]
