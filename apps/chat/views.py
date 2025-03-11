from rest_framework import viewsets
from rest_framework.decorators import action, permission_classes, api_view
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.db.models import Q
from .models import Conversation, Message, Delegate, Pharmacy, Visit, Feedback
from .models import Question, Answer, QAInteraction, QuestionCategory
from apps.whatsapp.services import WhatsAppService
from .tasks import process_message
from .services import ChatGPTService, ChatProcessor, QAService
from apps.agents.models import AgentProfile
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.contrib import messages
import json
import logging

from apps.chat import models

logger = logging.getLogger(__name__)

def login_view(request):
    """Vista para identificación de delegados antes de acceder al chat."""
    # Si se envió el formulario
    if request.method == 'POST':
        delegate_code = request.POST.get('delegate_code', '').strip()
        delegate_name = request.POST.get('delegate_name', '').strip()
        
        if not delegate_code or not delegate_name:
            messages.error(request, "Por favor, completa todos los campos.")
            return render(request, "chat/login.html")
        
        # Buscar o crear el delegado
        delegate, created = Delegate.objects.get_or_create(
            code=delegate_code,
            defaults={'name': delegate_name}
        )
        
        # Si no es nuevo pero el nombre no coincide, actualizar el nombre
        if not created and delegate.name != delegate_name:
            delegate.name = delegate_name
            delegate.save()
        
        # Actualizar última sesión
        delegate.last_login_at = timezone.now()
        delegate.save()
        
        # Guardar en sesión
        request.session['delegate_id'] = delegate.id
        
        # Si ya aceptó los términos, ir al chat directamente
        if delegate.terms_accepted:
            return redirect('chat')
        # Si no ha aceptado los términos, redirigir a la página de términos
        return redirect('terms')
    
    return render(request, "chat/login.html")

def terms_view(request):
    """Vista para aceptación de términos y condiciones."""
    # Verificar que el usuario esté identificado
    delegate_id = request.session.get('delegate_id')
    if not delegate_id:
        return redirect('login')
    
    delegate = get_object_or_404(Delegate, id=delegate_id)
    
    # Si ya aceptó los términos, ir al chat directamente
    if delegate.terms_accepted:
        return redirect('chat')
    
    # Si se envió el formulario
    if request.method == 'POST':
        accept_terms = request.POST.get('accept_terms') == 'on'
        
        if accept_terms:
            # Actualizar el delegado
            delegate.terms_accepted = True
            delegate.terms_accepted_at = timezone.now()
            delegate.save()
            
            messages.success(request, "Has aceptado los términos y condiciones.")
            return redirect('chat')
        else:
            messages.error(request, "Debes aceptar los términos y condiciones para continuar.")
    
    return render(request, "chat/terms.html", {"delegate": delegate})

@permission_classes([AllowAny])
def chat_view(request):
    try:
        # Verificar que el usuario esté identificado
        delegate_id = request.session.get('delegate_id')
        if not delegate_id:
            return redirect('login')
        
        delegate = get_object_or_404(Delegate, id=delegate_id)
        
        # Verificar que el usuario haya aceptado los términos
        if not delegate.terms_accepted:
            return redirect('terms')
            
        # Obtener conversaciones del delegado
        conversations = Conversation.objects.filter(delegate=delegate)
        conversation_id = request.GET.get('conversation_id')
        conversation = None
        
        # Lógica simplificada para obtener/crear una conversación válida
        if conversation_id:
            # Intentar obtener la conversación especificada
            try:
                conversation = conversations.get(id=conversation_id)
            except Conversation.DoesNotExist:
                # Si la conversación no existe para este delegado, mostramos un mensaje
                messages.error(request, "No tienes acceso a esta conversación.")
                conversation = None
        
        # Si no hay conversation_id o la conversación no existe para este delegado
        if not conversation:
            # Intentar usar la primera conversación existente
            conversation = conversations.first()
            
            # Si no hay ninguna conversación, crear una nueva
            if not conversation:
                # Obtener un agente disponible
                agent = AgentProfile.objects.filter(is_active=True).first()
                if not agent:
                    messages.error(request, "No hay agentes disponibles en este momento.")
                    return render(request, "chat/chat.html", {
                        "conversations": [],
                        "chat_messages": [],
                        "delegate": delegate
                    })
                
                # Crear conversación nueva
                try:
                    conversation = Conversation.objects.create(
                        agent=agent,
                        client_phone=f"delegado_{delegate.code}",
                        delegate=delegate,
                        is_active=True
                    )
                except Exception as e:
                    logger.error(f"Error al crear conversación: {str(e)}")
                    messages.error(request, "Error al crear una conversación nueva.")
                    return render(request, "chat/chat.html", {
                        "conversations": conversations,
                        "chat_messages": [],
                        "delegate": delegate
                    })
        
        # Ahora tenemos una conversación válida o ninguna si hubo un error
        if conversation:
            # Obtener mensajes de la conversación
            chat_messages = Message.objects.filter(conversation=conversation).order_by('timestamp')
            conversation_id = conversation.id
        else:
            chat_messages = []
            conversation_id = None
        
        # Renderizar la página del chat
        return render(request, "chat/chat.html", {
            "conversations": conversations,
            "chat_messages": chat_messages,
            "current_conversation_id": conversation_id,
            "delegate": delegate
        })
        
    except Exception as e:
        logger.error(f"Error en chat_view: {str(e)}")
        messages.error(request, "Error inesperado cargando el chat.")
        # En caso de error, intentar mostrar el login
        try:
            return redirect('login')
        except:
            return HttpResponse("Error al cargar el chat. Por favor, inténtelo de nuevo más tarde.")

class ConversationViewSet(viewsets.ModelViewSet):
    queryset = Conversation.objects.all()
    
    @action(detail=True, methods=['post'])
    def send_message(self, request, pk=None):
        conversation = self.get_object()
        content = request.data.get('content')
        
        message = Message.objects.create(
            conversation=conversation,
            content=content,
            direction='OUT'
        )
        
        whatsapp_service = WhatsAppService()
        whatsapp_service.send_message(conversation.client_phone, content)
        
        return Response({'status': 'message sent'})
    
    @action(detail=True, methods=['post'])
    def process_message(self, request, pk=None):
        message = Message.objects.get(pk=pk)
        process_message.delay(message.id)
        return Response({'status': 'processing'})

class ChatGPTView(APIView):
    def post(self, request):
        message = request.data.get('message')
        if not message:
            return Response(
                {'error': 'El mensaje es requerido'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        chat_service = ChatGPTService()
        response = chat_service.get_chat_response(message)
        
        return Response({'response': response})

@require_POST
def send_message(request):
    # Verificar que el usuario esté identificado
    delegate_id = request.session.get('delegate_id')
    if not delegate_id:
        return JsonResponse({"error": "Debe identificarse para enviar mensajes.", "redirect": "login"}, status=401)
    
    delegate = get_object_or_404(Delegate, id=delegate_id)
    
    # Verificar que el usuario haya aceptado los términos
    if not delegate.terms_accepted:
        return JsonResponse({"error": "Debe aceptar los términos y condiciones.", "redirect": "terms"}, status=403)
    
    conversation_id = request.POST.get('conversation_id')
    message_content = request.POST.get('message', '').strip()
    
    if not message_content:
        return JsonResponse({"error": "El mensaje no puede estar vacío."}, status=400)
    
    try:
        # Intentar obtener la conversación
        try:
            conversation = Conversation.objects.get(id=conversation_id, delegate=delegate)
        except Conversation.DoesNotExist:
            # Verificar si el usuario está intentando acceder a una conversación que no le pertenece
            if Conversation.objects.filter(id=conversation_id).exists():
                return JsonResponse({"error": "No tienes permiso para acceder a esta conversación."}, status=403)
            
            # Crear una nueva conversación
            agent = AgentProfile.objects.filter(is_active=True).first()
            if not agent:
                return JsonResponse({"error": "No hay agentes disponibles en este momento."}, status=400)
            
            conversation = Conversation.objects.create(
                agent=agent,
                client_phone=f"delegado_{delegate.code}",
                delegate=delegate,
                is_active=True
            )
        
        # Usar el chat processor para manejar el mensaje
        chat_processor = ChatProcessor()
        user_message, placeholder = chat_processor.handle_incoming_message(
            message_content, 
            conversation
        )
        
        # Procesar el mensaje en segundo plano
        process_message.delay(user_message.id, source='web')
        
        # Return a JSON response instead of redirecting
        return JsonResponse({
            "status": "success",
            "message": "Mensaje recibido y siendo procesado",
            "message_id": user_message.id,
            "placeholder_id": placeholder.id,
            "conversation_id": conversation.id
        })
    except Exception as e:
        logger.error(f"Error al procesar mensaje: {str(e)}")
        return JsonResponse({
            "error": "Error al procesar el mensaje", 
            "message": f"Lo sentimos, ha ocurrido un error: {str(e)}"
        }, status=500)

def conversation_detail(request, conversation_id):
    # Verificar que el usuario esté identificado
    delegate_id = request.session.get('delegate_id')
    if not delegate_id:
        return redirect('login')
    
    delegate = get_object_or_404(Delegate, id=delegate_id)
    
    # Verificar que el usuario haya aceptado los términos
    if not delegate.terms_accepted:
        return redirect('terms')
    
    try:
        conversation = Conversation.objects.get(id=conversation_id, delegate=delegate)
    except Conversation.DoesNotExist:
        messages.error(request, "No tienes permiso para acceder a esta conversación.")
        return redirect('chat')
    
    chat_messages = Message.objects.filter(conversation=conversation).order_by('timestamp')
    conversations = Conversation.objects.filter(delegate=delegate)
    
    return render(request, "chat/chat.html", {
        "conversation": conversation,
        "chat_messages": chat_messages,
        "conversations": conversations,
        "current_conversation_id": conversation_id,
        "delegate": delegate
    })

@csrf_exempt
@permission_classes([AllowAny])
def send_chat_message(request):
    """
    Handle chat message sending with proper flow control and context building.
    Only forwards to GPT after all required context is gathered.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido"}, status=405)
        
    try:
        data = json.loads(request.body)
        conversation_id = data.get("conversation_id")
        user_message = data.get("message")
        source = data.get("source", "web_api")  # Default source is web_api
        
        # Verify user authentication
        delegate_id = request.session.get('delegate_id')
        if not delegate_id:
            logger.error("Usuario no autenticado")
            return JsonResponse({"error": "Debe identificarse para enviar mensajes.", "redirect": "login"}, status=401)
        
        delegate = Delegate.objects.get(id=delegate_id)
        
        # Verify terms acceptance
        if not delegate.terms_accepted:
            logger.error("Términos no aceptados por el usuario")
            return JsonResponse({"error": "Debe aceptar los términos y condiciones.", "redirect": "terms"}, status=403)
        
        logger.info(f"Mensaje recibido de {delegate.name}: {user_message[:50]}...")
        
        if not user_message:
            logger.error("Mensaje vacío")
            return JsonResponse({"error": "El mensaje es requerido"}, status=400)
            
        # Get or create conversation
        conversation = None
        if conversation_id:
            try:
                conversation = Conversation.objects.get(id=conversation_id, delegate=delegate)
            except Conversation.DoesNotExist:
                logger.error("Conversación no encontrada")
                pass
                
        if not conversation:
            agent = AgentProfile.objects.filter(is_active=True).first()
            if not agent:
                logger.error("No hay agentes disponibles")
                return JsonResponse({"error": "No hay agentes disponibles", "message": "Lo sentimos, no hay agentes disponibles en este momento. Inténtalo más tarde."}, status=400)
            
            conversation = Conversation.objects.create(
                agent=agent,
                client_phone=f"delegado_{delegate.code}",
                delegate=delegate,
                is_active=True
            )
            logger.info(f"Nueva conversación creada con ID: {conversation.id}")
        
        # Usar el chat processor para manejar el mensaje
        chat_processor = ChatProcessor()
        user_message, placeholder = chat_processor.handle_incoming_message(
            user_message,
            conversation,
            source=source
        )
        logger.info(f"Mensaje guardado con ID: {user_message.id}, placeholder creado con ID: {placeholder.id}")
        
        # Procesar el mensaje en segundo plano
        process_message.delay(user_message.id, source=source)
        
        return JsonResponse({
            "status": "success",
            "message": "Mensaje recibido y siendo procesado",
            "message_id": user_message.id,
            "placeholder_id": placeholder.id,
            "conversation_id": conversation.id
        })
        
    except json.JSONDecodeError:
        logger.error("Formato de mensaje inválido")
        return JsonResponse({
            "error": "Formato de mensaje inválido", 
            "message": "Ha ocurrido un error con el formato del mensaje. Por favor, intenta de nuevo."
        }, status=400)
        
    except Exception as e:
        logger.error(f"Error inesperado: {str(e)}")
        return JsonResponse({
            "error": str(e), 
            "message": "Lo sentimos, ha ocurrido un error al procesar tu mensaje. Por favor, intenta de nuevo en unos momentos."
        }, status=500)

@csrf_exempt
@permission_classes([AllowAny])
def get_conversation_messages(request):
    """Endpoint para obtener todos los mensajes de una conversación."""
    # Verificar que el usuario esté identificado
    delegate_id = request.session.get('delegate_id')
    if not delegate_id:
        return JsonResponse({"error": "Debe identificarse para ver los mensajes."}, status=401)
    
    delegate = Delegate.objects.filter(id=delegate_id).first()
    if not delegate:
        return JsonResponse({"error": "Delegado no encontrado."}, status=401)
    
    # Verificar que el usuario haya aceptado los términos
    if not delegate.terms_accepted:
        return JsonResponse({"error": "Debe aceptar los términos y condiciones."}, status=403)
    
    conversation_id = request.GET.get('conversation_id')
    
    if not conversation_id:
        logger.error("No se proporcionó conversation_id")
        return JsonResponse({"error": "conversation_id is required"}, status=400)
    
    try:
        # Verificar que la conversación pertenezca al delegado
        try:
            conversation = Conversation.objects.get(id=conversation_id, delegate=delegate)
        except Conversation.DoesNotExist:
            return JsonResponse({"error": "No tiene permiso para acceder a esta conversación."}, status=403)
        
        # Obtener todos los mensajes de la conversación ordenados por timestamp
        messages = Message.objects.filter(
            conversation_id=conversation_id
        ).order_by('timestamp')
        
        # Check which messages were answered using Q&A system
        qa_interactions = QAInteraction.objects.filter(
            conversation=conversation
        ).values_list('user_query', flat=True)
        
        # Serializar los mensajes
        messages_data = []
        for msg in messages:
            message_data = {
                'id': msg.id,
                'content': msg.content,
                'direction': msg.direction,
                'timestamp': msg.timestamp.isoformat(),
                'ai_processed': msg.ai_processed,
                'qa_response': False
            }
            
            # If this is an outgoing message and has been processed by AI
            if msg.direction == 'OUT' and msg.ai_processed:
                # Check if we can find a QA interaction for this message
                qa_interaction = QAInteraction.objects.filter(
                    conversation=conversation,
                    provided_answer__text=msg.content
                ).first()
                
                if qa_interaction:
                    message_data['qa_response'] = True
                    message_data['qa_confidence'] = qa_interaction.success_rate
            
            messages_data.append(message_data)
        
        return JsonResponse({
            "messages": messages_data,
            "conversation_id": conversation_id
        })
        
    except Exception as e:
        logger.error(f"Error obteniendo mensajes de la conversación: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@permission_classes([AllowAny])
def get_latest_response(request):
    """Endpoint para obtener la última respuesta de la IA al mensaje enviado."""
    # Verificar que el usuario esté identificado
    delegate_id = request.session.get('delegate_id')
    if not delegate_id:
        return JsonResponse({"error": "Debe identificarse para ver los mensajes."}, status=401)
    
    delegate = Delegate.objects.filter(id=delegate_id).first()
    if not delegate:
        return JsonResponse({"error": "Delegado no encontrado."}, status=401)
    
    # Verificar que el usuario haya aceptado los términos
    if not delegate.terms_accepted:
        return JsonResponse({"error": "Debe aceptar los términos y condiciones."}, status=403)
    
    conversation_id = request.GET.get('conversation_id')
    
    if not conversation_id:
        logger.error("No se proporcionó conversation_id")
        return JsonResponse({"error": "conversation_id is required"}, status=400)
    
    try:
        # Verificar que la conversación pertenezca al delegado
        try:
            conversation = Conversation.objects.get(id=conversation_id, delegate=delegate)
        except Conversation.DoesNotExist:
            return JsonResponse({"error": "No tiene permiso para acceder a esta conversación."}, status=403)
        
        logger.debug(f"Buscando última respuesta para conversación {conversation_id}")
        
        # Primero, buscar el mensaje más reciente que está siendo procesado
        processing_message = Message.objects.filter(
            conversation_id=conversation_id,
            direction='OUT',
            content="Procesando respuesta..."
        ).order_by('-timestamp').first()
        
        if processing_message:
            return JsonResponse({"response": None}, status=200)
            
        # Si no hay mensaje en procesamiento, buscar la última respuesta procesada
        latest_response = Message.objects.filter(
            conversation_id=conversation_id,
            direction='OUT'
        ).exclude(
            content="Procesando respuesta..."
        ).order_by('-timestamp').first()
        
        if latest_response:
            logger.info(f"Respuesta encontrada: {latest_response.id}")
            return JsonResponse({
                "response": latest_response.content,
                "timestamp": latest_response.timestamp.isoformat(),
                "message_id": latest_response.id
            })
        else:
            logger.info(f"No se encontraron respuestas para conversación {conversation_id}")
            return JsonResponse({"response": None}, status=200)
            
    except Exception as e:
        logger.error(f"Error obteniendo última respuesta: {str(e)}")
        return JsonResponse({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([AllowAny])
def search_pharmacies(request):
    """Endpoint para buscar farmacias con información detallada."""
    query = request.query_params.get('q', '')
    
    if len(query) < 3:
        return Response({"error": "La búsqueda debe tener al menos 3 caracteres"}, status=status.HTTP_400_BAD_REQUEST)
    
    pharmacies = Pharmacy.objects.filter(
        Q(name__icontains=query) | 
        Q(address__icontains=query)
    )[:10]
    
    results = []
    for pharmacy in pharmacies:
        # Get last visit if any
        last_visit = Visit.objects.filter(
            pharmacy=pharmacy
        ).order_by('-visit_date').first()
        
        pharmacy_data = {
            'id': pharmacy.id,
            'name': pharmacy.name,
            'address': pharmacy.address,
            'last_visit_date': last_visit.visit_date.isoformat() if last_visit else None
        }
        results.append(pharmacy_data)
    
    return Response(results)

@api_view(['POST'])
@permission_classes([AllowAny])
def submit_visit_feedback(request):
    """Endpoint para enviar feedback de una visita."""
    visit_id = request.data.get('visit_id')
    feedback_type = request.data.get('feedback_type')
    feedback_text = request.data.get('feedback_text')
    audio_file = request.FILES.get('audio_file')
    
    if not visit_id or not feedback_type:
        return Response({
            "error": "Se requieren visit_id y feedback_type"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        visit = Visit.objects.get(id=visit_id)
    except Visit.DoesNotExist:
        return Response({"error": "Visita no encontrada"}, status=status.HTTP_404_NOT_FOUND)
    
    if feedback_type == 'TEXT' and not feedback_text:
        return Response({
            "error": "Se requiere texto para feedback tipo TEXT"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    if feedback_type == 'AUDIO' and not audio_file:
        return Response({
            "error": "Se requiere archivo de audio para feedback tipo AUDIO"
        }, status=status.HTTP_400_BAD_REQUEST)
    
    feedback = Feedback.objects.create(
        visit=visit,
        feedback_type=feedback_type,
        feedback_text=feedback_text,
        audio_file=audio_file
    )
    
    return Response({
        "message": "Feedback guardado exitosamente",
        "feedback_id": feedback.id
    })

@api_view(['GET'])
@permission_classes([AllowAny])
def get_visit_summary(request, visit_id):
    """Endpoint para obtener el resumen de una visita."""
    try:
        visit = Visit.objects.select_related('pharmacy', 'delegate').get(id=visit_id)
    except Visit.DoesNotExist:
        return Response({"error": "Visita no encontrada"}, status=status.HTTP_404_NOT_FOUND)

    # Obtener feedbacks
    feedbacks = visit.feedbacks.all()
    
    summary = {
        'visit_id': visit.id,
        'pharmacy': {
            'id': visit.pharmacy.id,
            'name': visit.pharmacy.name,
            'address': visit.pharmacy.address
        },
        'delegate': {
            'id': visit.delegate.id,
            'name': visit.delegate.name,
            'code': visit.delegate.code
        },
        'visit_date': visit.visit_date.isoformat(),
        'status': visit.get_status_display(),
        'notes': visit.notes,
        'next_visit_date': visit.next_visit_date.isoformat() if visit.next_visit_date else None,
        'next_visit_reminder': visit.next_visit_reminder,
        'feedbacks': [{
            'id': f.id,
            'type': f.get_feedback_type_display(),
            'text': f.feedback_text,
            'audio_url': f.audio_file.url if f.audio_file else None,
            'created_at': f.created_at.isoformat()
        } for f in feedbacks],
        'summary_confirmed': visit.summary_confirmed
    }
    
    return Response(summary)

@api_view(['POST'])
@permission_classes([AllowAny])
def confirm_visit_summary(request, visit_id):
    """Endpoint para confirmar el resumen de una visita."""
    try:
        visit = Visit.objects.get(id=visit_id)
    except Visit.DoesNotExist:
        return Response({"error": "Visita no encontrada"}, status=status.HTTP_404_NOT_FOUND)
    
    visit.summary_confirmed = True
    visit.status = 'COMPLETED'
    visit.save()
    
    return Response({
        "message": "Resumen confirmado exitosamente",
        "visit_id": visit.id
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def generate_visit_report(request, visit_id):
    """
    Generate a structured report for a visit using ChatGPT.
    This is called after all visit data has been collected and validated.
    """
    try:
        visit = Visit.objects.select_related('pharmacy', 'delegate').get(id=visit_id)
    except Visit.DoesNotExist:
        return Response({"error": "Visita no encontrada"}, status=status.HTTP_404_NOT_FOUND)

    # Gather all visit data for the report
    visit_data = {
        'pharmacy': {
            'name': visit.pharmacy.name,
            'address': visit.pharmacy.address,
            'phone': visit.pharmacy.phone,
            'email': visit.pharmacy.email,
            'revenue': str(visit.pharmacy.revenue) if visit.pharmacy.revenue else None,
        },
        'delegate': {
            'name': visit.delegate.name,
            'code': visit.delegate.code
        },
        'visit_date': visit.visit_date.isoformat(),
        'status': visit.get_status_display(),
        'notes': visit.notes,
        'next_visit_reminder': visit.next_visit_reminder,
        'next_visit_date': visit.next_visit_date.isoformat() if visit.next_visit_date else None
    }

    # Add feedback history
    feedbacks = visit.feedbacks.all()
    feedback_history = []
    for feedback in feedbacks:
        feedback_entry = {
            'type': feedback.get_feedback_type_display(),
            'text': feedback.feedback_text if feedback.feedback_type == 'TEXT' else 'Audio feedback disponible',
            'created_at': feedback.created_at.isoformat()
        }
        feedback_history.append(feedback_entry)
    
    visit_data['feedback'] = feedback_history

    # Get previous visits to this pharmacy
    previous_visits = Visit.objects.filter(
        pharmacy=visit.pharmacy,
        visit_date__lt=visit.visit_date
    ).order_by('-visit_date')[:3]

    visit_data['previous_visits'] = [{
        'date': v.visit_date.isoformat(),
        'status': v.get_status_display(),
        'notes': v.notes
    } for v in previous_visits]

    # Generate report using GPT
    chatgpt_service = ChatGPTService()
    report = chatgpt_service.generate_visit_report(visit_data)

    # Save the report
    visit.notes = report
    visit.save()

    return Response({
        "message": "Reporte generado exitosamente",
        "visit_id": visit.id,
        "report": report
    })

def visit_summary_view(request, visit_id):
    """Vista para mostrar y gestionar el resumen de una visita."""
    # Verificar que el usuario esté identificado
    delegate_id = request.session.get('delegate_id')
    if not delegate_id:
        return redirect('login')
    
    delegate = get_object_or_404(Delegate, id=delegate_id)
    
    # Verificar que el usuario haya aceptado los términos
    if not delegate.terms_accepted:
        return redirect('terms')
    
    # Obtener la visita y verificar que pertenezca al delegado
    visit = get_object_or_404(Visit, id=visit_id, delegate=delegate)
    
    return render(request, "chat/visit_summary.html", {
        "visit": visit,
        "delegate": delegate
    })

@api_view(['GET'])
@permission_classes([AllowAny])
def debug_latest_response(request, conversation_id):
    """
    Endpoint para ver la última respuesta directamente para depuración.
    Muestra el contenido de la última respuesta en la conversación.
    """
    try:
        conversation = Conversation.objects.get(id=conversation_id)
        
        # Obtener la última respuesta (OUT)
        latest_response = Message.objects.filter(
            conversation=conversation,
            direction='OUT'
        ).exclude(
            content__startswith="__STATE__:"
        ).exclude(
            content__startswith="__DATA__:"
        ).exclude(
            content="Procesando respuesta..."
        ).order_by('-timestamp').first()
        
        if latest_response:
            return Response({
                'id': latest_response.id,
                'content': latest_response.content,
                'timestamp': latest_response.timestamp,
                'is_processed': latest_response.ai_processed
            })
        
        return Response({'error': 'No hay respuestas disponibles'}, status=404)
        
    except Conversation.DoesNotExist:
        return Response({'error': 'Conversación no encontrada'}, status=404)

# Q&A API Views
@api_view(['POST'])
@permission_classes([AllowAny])
def query_qa(request):
    """
    Endpoint to query the Q&A system directly without going through the chat flow.
    """
    user_query = request.data.get('query')
    conversation_id = request.data.get('conversation_id')
    
    if not user_query:
        return Response({"error": "Query is required"}, status=status.HTTP_400_BAD_REQUEST)
    
    # Get delegate from session
    delegate_id = request.session.get('delegate_id')
    delegate = None
    if delegate_id:
        delegate = Delegate.objects.filter(id=delegate_id).first()
    
    # Get or create conversation if needed
    conversation = None
    if conversation_id:
        try:
            conversation = Conversation.objects.get(id=conversation_id)
        except Conversation.DoesNotExist:
            return Response({"error": "Conversation not found"}, status=status.HTTP_404_NOT_FOUND)
    else:
        # Create a temporary conversation for standalone queries
        agent = AgentProfile.objects.filter(is_active=True).first()
        if not agent:
            return Response({"error": "No agents available"}, status=status.HTTP_400_BAD_REQUEST)
        
        conversation = Conversation.objects.create(
            agent=agent,
            client_phone="qa_standalone",
            is_active=True,
            delegate=delegate
        )
    
    # Process query
    qa_service = QAService(delegate=delegate)
    result = qa_service.process_query(user_query, conversation)
    
    if not result['success']:
        return Response({
            "success": False,
            "message": "No matching question found"
        }, status=status.HTTP_404_NOT_FOUND)
    
    return Response({
        "success": True,
        "question_id": result['question_id'],
        "answer": result['response'],
        "confidence": result['confidence']
    })

@api_view(['GET'])
@permission_classes([AllowAny])
def get_qa_statistics(request):
    """
    Get statistics about Q&A system usage.
    """
    total_questions = Question.objects.count()
    total_answers = Answer.objects.count()
    total_interactions = QAInteraction.objects.count()
    
    # Get success rate distribution
    success_rates = QAInteraction.objects.values_list('success_rate', flat=True)
    avg_success_rate = sum(success_rates) / len(success_rates) if success_rates else 0
    
    # Get most frequently matched questions
    top_questions = QAInteraction.objects.values('matched_question').annotate(
        count=models.Count('matched_question')
    ).order_by('-count')[:5]
    
    top_questions_data = []
    for item in top_questions:
        if item['matched_question']:
            try:
                question = Question.objects.get(id=item['matched_question'])
                top_questions_data.append({
                    'id': question.id,
                    'text': question.text,
                    'count': item['count']
                })
            except Question.DoesNotExist:
                pass
    
    return Response({
        'total_questions': total_questions,
        'total_answers': total_answers,
        'total_interactions': total_interactions,
        'avg_success_rate': avg_success_rate,
        'top_questions': top_questions_data
    })

@api_view(['POST'])
@permission_classes([AllowAny])
def provide_feedback(request, interaction_id):
    """
    Endpoint for users to provide feedback on Q&A interactions.
    """
    feedback_text = request.data.get('feedback')
    
    try:
        interaction = QAInteraction.objects.get(id=interaction_id)
    except QAInteraction.DoesNotExist:
        return Response({"error": "Interaction not found"}, status=status.HTTP_404_NOT_FOUND)
    
    interaction.feedback = feedback_text
    interaction.save()
    
    return Response({
        "success": True,
        "message": "Feedback received, thank you!"
    })

# Add Q&A management viewset
class QuestionViewSet(viewsets.ModelViewSet):
    queryset = Question.objects.all()
    
    @action(detail=True, methods=['GET'])
    def answers(self, request, pk=None):
        question = self.get_object()
        answers = question.answers.all()
        return Response([{
            'id': answer.id,
            'text': answer.text,
            'is_default': answer.is_default
        } for answer in answers])
    
    @action(detail=True, methods=['POST'])
    def add_answer(self, request, pk=None):
        question = self.get_object()
        text = request.data.get('text')
        is_default = request.data.get('is_default', False)
        
        if not text:
            return Response({"error": "Answer text is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        # If this is going to be default, clear the previous default
        if is_default:
            question.answers.filter(is_default=True).update(is_default=False)
        
        answer = Answer.objects.create(
            question=question,
            text=text,
            is_default=is_default
        )
        
        return Response({
            'id': answer.id,
            'text': answer.text,
            'is_default': answer.is_default
        })