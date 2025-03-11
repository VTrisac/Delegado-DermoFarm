import traceback
import openai
import re
from django.conf import settings
from typing import Dict, Any, Optional, Tuple, List
from django.db.models import Q
from apps.chat.models import InteractionLog, Message, Conversation, Pharmacy, Visit, Feedback, Delegate
from apps.chat.models import Question, Answer, QAInteraction, QuestionCategory
import logging
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

class ChatGPTService:
    def __init__(self):
        openai.api_key = settings.OPENAI_API_KEY
        self.config = settings.OPENAI_CONFIG
        logger.info("ChatGPTService initialized with model: %s", self.config['model'])

    def process_message(self, message: str, context: Dict[str, Any] = None) -> str:
        try:
            messages = [
                {"role": "system", "content": self.config['system_prompt']},
            ]

            if context:
                # Add user authentication context
                if 'delegate' in context:
                    messages.append({
                        "role": "system",
                        "content": f"Usuario autenticado: {context['delegate']['name']} (Código: {context['delegate']['code']})"
                    })

                # Add pharmacy context if available
                if 'pharmacy' in context:
                    pharmacy_info = f"""
                    Farmacia: {context['pharmacy']['name']}
                    Dirección: {context['pharmacy']['address']}
                    Última visita: {context['pharmacy']['last_visit'] or 'Sin visitas previas'}
                    """
                    messages.append({
                        "role": "system",
                        "content": pharmacy_info
                    })

                # Add visits context if available
                if 'visits' in context:
                    visits_info = "Historial de visitas:\n"
                    for visit in context['visits']:
                        visits_info += f"- {visit['date']}: {visit['status']}\n"
                    messages.append({
                        "role": "system",
                        "content": visits_info
                    })

                # Add conversation history
                if 'history' in context:
                    for msg in context['history']:
                        messages.append({
                            "role": "user" if msg['direction'] == 'IN' else "assistant",
                            "content": msg['content']
                        })

            messages.append({"role": "user", "content": message})
            
            logger.debug("Sending request to OpenAI with %d messages", len(messages))
            
            response = openai.ChatCompletion.create(
                model=self.config['model'],
                messages=messages,
                temperature=self.config.get('temperature', 0.7),
                max_tokens=self.config.get('max_tokens', 150),
                timeout=30
            )
            
            response_content = response['choices'][0]['message']['content']
            logger.info("Successfully received response from OpenAI")
            return response_content
            
        except openai.error.AuthenticationError as e:
            logger.error("Authentication error with OpenAI: %s", str(e))
            return "Lo siento, hay un problema de autenticación con el servicio. Por favor, contacta al administrador."
            
        except openai.error.APIError as e:
            logger.error("OpenAI API error: %s", str(e))
            return "Lo siento, hubo un error al procesar tu mensaje. Por favor, intenta de nuevo más tarde."
            
        except openai.error.Timeout as e:
            logger.error("OpenAI timeout error: %s", str(e))
            return "El servicio está tardando demasiado en responder. Por favor, intenta de nuevo."
            
        except Exception as e:
            logger.error("Unexpected error in ChatGPT service: %s", str(e))
            return "Lo siento, ocurrió un error inesperado. Por favor, intenta de nuevo más tarde."

    def get_product_recommendation(self, symptoms: str) -> str:
        prompt = f"""Por favor, recomienda productos DermoFarm apropiados para los 
        siguientes síntomas o condiciones: {symptoms}. 
        Incluye una breve explicación de por qué recomiendar cada producto."""

        return self.process_message(prompt)

    def get_chat_response(self, message: str, model: str = None) -> str:
        if not model:
            model = self.config['model']
            
        return self.process_message(message)

    def generate_visit_report(self, visit_data: Dict[str, Any]) -> str:
        """Generate a structured report based on visit data"""
        prompt = f"""Por favor, genera un informe detallado de la visita con la siguiente información:

        Farmacia: {visit_data['pharmacy']['name']}
        Dirección: {visit_data['pharmacy']['address']}
        Fecha de visita: {visit_data['visit_date']}
        Delegado: {visit_data['delegate']['name']}

        Historial de feedback:
        {visit_data.get('feedback', 'Sin feedback registrado')}

        Por favor, incluye:
        1. Resumen de la visita
        2. Puntos clave observados
        3. Recomendaciones para próximas visitas
        4. Acciones de seguimiento sugeridas
        """
        
        return self.process_message(prompt)


class SmartResponseEngine:
    """
    Engine for generating intelligent responses from the backend
    without immediately relying on GPT.
    
    This class analyzes user messages, extracts intents, and generates
    appropriate contextual responses based on database information.
    """
    
    # Intent patterns for message classification
    INTENT_PATTERNS = {
        'greeting': r'\b(hola|buenos días|buenas tardes|saludos|hey)\b',
        'pharmacy_search': r'\b(farmacia|farmacias|botica|droguería)\b',
        'visit_info': r'\b(visita|visitar|visitando|visitado)\b', 
        'feedback': r'\b(feedback|comentario|opinión|valoración|retroalimentación)\b',
        'report': r'\b(informe|reporte|resumen)\b',
        'help': r'\b(ayuda|ayúdame|como|cómo|instrucciones|opciones)\b'
    }
    
    # Session states to track conversation flow
    SESSION_STATES = {
        'INITIAL': 'initial',
        'AWAITING_PHARMACY': 'awaiting_pharmacy',
        'PHARMACY_SELECTED': 'pharmacy_selected',
        'AWAITING_VISIT_ACTION': 'awaiting_visit_action',
        'COLLECTING_FEEDBACK': 'collecting_feedback',
        'READY_FOR_REPORT': 'ready_for_report'
    }
    
    # Default responses for different scenarios
    DEFAULT_RESPONSES = {
        'unknown': "Lo siento, no he entendido completamente tu mensaje. ¿Podrías ser más específico? Puedes preguntar sobre farmacias, visitas o solicitar ayuda escribiendo 'ayuda'.",
        'error': "Lo siento, ha ocurrido un error procesando tu mensaje. Por favor, inténtalo de nuevo o escribe 'ayuda' para ver las opciones disponibles.",
        'timeout': "Parece que estoy tardando en procesar tu solicitud. Por favor, intenta con un mensaje más claro o escribe 'ayuda' para ver las opciones disponibles."
    }
    
    def __init__(self, conversation: Conversation):
        self.conversation = conversation
        self.delegate = conversation.delegate
        
        # Initialize or get current session state
        self.session_state = self._get_session_state()
        self.session_data = self._get_session_data()
        
        logger.info(f"SmartResponseEngine initialized with state: {self.session_state}")
    
    def _get_session_state(self) -> str:
        """Retrieve current conversation state or initialize it"""
        # Check if we have a state message in the conversation
        state_message = Message.objects.filter(
            conversation=self.conversation,
            content__startswith="__STATE__:"
        ).order_by('-timestamp').first()
        
        if state_message:
            try:
                return state_message.content.split(":", 1)[1].strip()
            except (IndexError, AttributeError):
                pass
        
        return self.SESSION_STATES['INITIAL']
    
    def _get_session_data(self) -> Dict:
        """Retrieve session data or initialize it"""
        # Check if we have a data message in the conversation
        data_message = Message.objects.filter(
            conversation=self.conversation,
            content__startswith="__DATA__:"
        ).order_by('-timestamp').first()
        
        if data_message:
            try:
                import json
                data_str = data_message.content.split(":", 1)[1].strip()
                return json.loads(data_str)
            except (IndexError, AttributeError, json.JSONDecodeError):
                pass
        
        return {}
    
    def _save_session_state(self, state: str) -> None:
        """Save current session state"""
        Message.objects.create(
            conversation=self.conversation,
            content=f"__STATE__:{state}",
            direction='OUT',
            ai_processed=True
        )
        self.session_state = state
    
    def _save_session_data(self, data: Dict) -> None:
        """Save session data"""
        import json
        Message.objects.create(
            conversation=self.conversation,
            content=f"__DATA__:{json.dumps(data)}",
            direction='OUT',
            ai_processed=True
        )
        self.session_data = data
    
    def _detect_intent(self, message: str) -> str:
        """Detect the primary intent from user message"""
        message = message.lower()
        
        for intent, pattern in self.INTENT_PATTERNS.items():
            if re.search(pattern, message):
                return intent
        
        return 'unknown'
    
    def _search_pharmacy(self, message: str) -> List[Dict]:
        """Search for pharmacies based on user input"""
        terms = message.lower().replace('farmacia', '').strip()
        if len(terms) < 3:
            return []
        
        # Search for pharmacies by name or address
        pharmacies = Pharmacy.objects.filter(
            Q(name__icontains=terms) | 
            Q(address__icontains=terms)
        )[:5]
        
        return [{
            'id': pharmacy.id,
            'name': pharmacy.name,
            'address': pharmacy.address,
            'last_visit': pharmacy.last_visit.strftime('%d/%m/%Y') if pharmacy.last_visit else 'Sin visitas previas'
        } for pharmacy in pharmacies]
    
    def _get_pharmacy_details(self, pharmacy_id: int) -> Optional[Dict]:
        """Get detailed information about a pharmacy"""
        try:
            pharmacy = Pharmacy.objects.get(id=pharmacy_id)
            
            # Get last visit if any
            last_visit = Visit.objects.filter(
                pharmacy=pharmacy,
                delegate=self.delegate
            ).order_by('-visit_date').first()
            
            return {
                'id': pharmacy.id,
                'name': pharmacy.name,
                'address': pharmacy.address,
                'phone': pharmacy.phone,
                'email': pharmacy.email,
                'last_visit_date': last_visit.visit_date.strftime('%d/%m/%Y') if last_visit else None,
                'last_visit_status': last_visit.get_status_display() if last_visit else None,
                'last_visit_id': last_visit.id if last_visit else None,
                'has_pending_visit': last_visit.status == 'PENDING' if last_visit else False
            }
        except Pharmacy.DoesNotExist:
            return None
    
    def _get_visit_options(self, pharmacy_id: int) -> Dict:
        """Get visit options for a pharmacy"""
        try:
            pharmacy = Pharmacy.objects.get(id=pharmacy_id)
            
            # Check for existing visits
            visits = Visit.objects.filter(
                pharmacy=pharmacy,
                delegate=self.delegate
            ).order_by('-visit_date')[:3]
            
            has_pending_visit = visits.filter(status='PENDING').exists()
            
            return {
                'pharmacy_name': pharmacy.name,
                'can_create_visit': not has_pending_visit,
                'has_pending_visit': has_pending_visit,
                'pending_visit_id': visits.filter(status='PENDING').first().id if has_pending_visit else None,
                'recent_visits': [{
                    'id': visit.id,
                    'date': visit.visit_date.strftime('%d/%m/%Y'),
                    'status': visit.get_status_display()
                } for visit in visits]
            }
        except Pharmacy.DoesNotExist:
            return {
                'pharmacy_name': 'Desconocida',
                'can_create_visit': False,
                'has_pending_visit': False,
                'recent_visits': []
            }
    
    def process_message(self, message_text: str) -> str:
        """
        Process a user message and generate a dynamic response.
        Always returns a response string, never None.
        """
        try:
            # Detect the user's intent
            intent = self._detect_intent(message_text)
            
            # Handle greetings directly
            if intent == 'greeting':
                if self.delegate:
                    return f"Hola {self.delegate.name}, ¿en qué puedo ayudarte hoy? Puedes buscar una farmacia, consultar visitas previas, o dejar feedback sobre una visita."
                else:
                    return "Hola, ¿en qué puedo ayudarte hoy? Por favor, identifícate para continuar."
            
            # Handle help requests directly
            if intent == 'help':
                return ("Puedo ayudarte con lo siguiente:\n"
                       "- Buscar información de farmacias (ej: 'farmacia centro')\n"
                       "- Consultar tus visitas a farmacias (ej: 'visitas recientes')\n"
                       "- Registrar feedback de visitas (ej: 'quiero dejar feedback')\n"
                       "- Generar reportes de visita (ej: 'generar informe')\n\n"
                       "¿Con qué necesitas ayuda hoy?")
            
            # Handle based on current session state
            if self.session_state == self.SESSION_STATES['INITIAL']:
                # Check if user is searching for a pharmacy
                if intent == 'pharmacy_search':
                    pharmacies = self._search_pharmacy(message_text)
                    
                    if pharmacies:
                        # Update session state
                        self._save_session_state(self.SESSION_STATES['AWAITING_PHARMACY'])
                        self._save_session_data({'pharmacies': pharmacies})
                        
                        # Format response
                        response = "Encontré las siguientes farmacias:\n\n"
                        for i, pharmacy in enumerate(pharmacies, 1):
                            response += f"{i}. {pharmacy['name']} - {pharmacy['address']}\n"
                        
                        response += "\nPor favor, responde con el número de la farmacia que te interesa, o escribe 'buscar' seguido del nombre para realizar otra búsqueda."
                        return response
                    else:
                        return "No encontré farmacias con ese nombre o dirección. Por favor, intenta con otro término de búsqueda más específico."
                
                # Handle visit intent from initial state
                elif intent == 'visit_info':
                    return "Para consultar información de visitas, primero necesito saber a qué farmacia te refieres. Por favor, búscala escribiendo 'farmacia' seguido del nombre."
                
                # Handle feedback intent from initial state
                elif intent == 'feedback':
                    return "Para dejar feedback de una visita, primero necesito saber a qué farmacia te refieres. Por favor, búscala escribiendo 'farmacia' seguido del nombre."
            
            # Handle pharmacy selection
            elif self.session_state == self.SESSION_STATES['AWAITING_PHARMACY']:
                # Check if user selected a pharmacy by number
                if message_text.isdigit():
                    selection = int(message_text)
                    if 'pharmacies' in self.session_data and 1 <= selection <= len(self.session_data['pharmacies']):
                        pharmacy = self.session_data['pharmacies'][selection-1]
                        
                        # Get detailed pharmacy info
                        pharmacy_details = self._get_pharmacy_details(pharmacy['id'])
                        
                        # Update session
                        self._save_session_state(self.SESSION_STATES['PHARMACY_SELECTED'])
                        self._save_session_data({'selected_pharmacy': pharmacy_details})
                        
                        response = f"Has seleccionado: {pharmacy['name']}\n"
                        response += f"Dirección: {pharmacy['address']}\n"
                        
                        if pharmacy_details['last_visit_date']:
                            response += f"Última visita: {pharmacy_details['last_visit_date']} - {pharmacy_details['last_visit_status']}\n\n"
                        else:
                            response += "No hay visitas previas registradas.\n\n"
                        
                        response += "¿Qué deseas hacer?\n"
                        response += "1. Registrar una nueva visita\n"
                        response += "2. Consultar visitas anteriores\n"
                        response += "3. Dejar feedback\n"
                        response += "4. Generar informe"
                        
                        return response
                    else:
                        return "Por favor, selecciona un número válido de la lista de farmacias."
                
                # Handle new search request
                elif message_text.lower().startswith('buscar'):
                    search_term = message_text[6:].strip()
                    if len(search_term) >= 3:
                        pharmacies = self._search_pharmacy(search_term)
                        
                        if pharmacies:
                            self._save_session_data({'pharmacies': pharmacies})
                            
                            response = "Encontré las siguientes farmacias:\n\n"
                            for i, pharmacy in enumerate(pharmacies, 1):
                                response += f"{i}. {pharmacy['name']} - {pharmacy['address']}\n"
                            
                            response += "\nPor favor, responde con el número de la farmacia que te interesa."
                            return response
                        else:
                            return "No encontré farmacias con ese nombre o dirección. Por favor, intenta con otro término de búsqueda."
                    else:
                        return "Por favor, proporciona al menos 3 caracteres para la búsqueda."
            
            # Handle actions after pharmacy is selected
            elif self.session_state == self.SESSION_STATES['PHARMACY_SELECTED']:
                if message_text.isdigit():
                    selection = int(message_text)
                    
                    # Get selected pharmacy
                    pharmacy = self.session_data.get('selected_pharmacy', {})
                    
                    if selection == 1:  # Register new visit
                        if pharmacy.get('has_pending_visit'):
                            visit_id = pharmacy.get('last_visit_id')
                            return f"Ya tienes una visita pendiente para esta farmacia. Puedes acceder a ella aquí: /visits/{visit_id}/"
                        else:
                            # Here we would create a new visit and redirect to it
                            # For now, we'll just simulate the response
                            new_visit = Visit.objects.create(
                                delegate=self.delegate,
                                pharmacy_id=pharmacy.get('id'),
                                status='PENDING'
                            )
                            
                            self._save_session_state(self.SESSION_STATES['AWAITING_VISIT_ACTION'])
                            self._save_session_data({
                                'selected_pharmacy': pharmacy,
                                'current_visit_id': new_visit.id
                            })
                            
                            return f"He creado una nueva visita para la farmacia {pharmacy.get('name')}. Puedes completar los detalles en: /visits/{new_visit.id}/"
                    
                    elif selection == 2:  # View previous visits
                        if 'id' in pharmacy:
                            visit_options = self._get_visit_options(pharmacy['id'])
                            
                            if visit_options['recent_visits']:
                                response = f"Visitas recientes a {visit_options['pharmacy_name']}:\n\n"
                                for i, visit in enumerate(visit_options['recent_visits'], 1):
                                    response += f"{i}. {visit['date']} - {visit['status']}\n"
                                return response
                            else:
                                return f"No hay visitas registradas para {visit_options['pharmacy_name']}."
                    
                    elif selection == 3:  # Leave feedback
                        if pharmacy.get('has_pending_visit'):
                            visit_id = pharmacy.get('last_visit_id')
                            self._save_session_state(self.SESSION_STATES['COLLECTING_FEEDBACK'])
                            self._save_session_data({
                                'selected_pharmacy': pharmacy,
                                'feedback_visit_id': visit_id
                            })
                            return f"Puedes dejar feedback para la visita pendiente. ¿Prefieres feedback en texto o audio? Responde 'texto' o 'audio'."
                        else:
                            return "No hay visitas pendientes para dejar feedback. Primero debes registrar una visita."
                    
                    elif selection == 4:  # Generate report
                        if 'id' in pharmacy:
                            # Check if we have enough data for a report
                            visit_options = self._get_visit_options(pharmacy['id'])
                            
                            if visit_options['recent_visits']:
                                self._save_session_state(self.SESSION_STATES['READY_FOR_REPORT'])
                                self._save_session_data({
                                    'selected_pharmacy': pharmacy,
                                    'visits': visit_options['recent_visits']
                                })
                                return "Tenemos suficiente información para generar un informe usando GPT. ¿Deseas continuar con la generación del informe?"
                            else:
                                return "No hay suficientes datos de visitas para generar un informe completo."
                
                return "Por favor selecciona una opción válida (1-4) o escribe 'salir' para volver al inicio."
            
            # Handle collecting feedback
            elif self.session_state == self.SESSION_STATES['COLLECTING_FEEDBACK']:
                visit_id = self.session_data.get('feedback_visit_id')
                
                if not visit_id:
                    self._save_session_state(self.SESSION_STATES['INITIAL'])
                    return "Ha ocurrido un error con la sesión. Por favor, comienza de nuevo."
                
                feedback_type = None
                if 'texto' in message_text.lower():
                    feedback_type = 'TEXT'
                    self._save_session_data({
                        **self.session_data,
                        'feedback_type': 'TEXT'
                    })
                    return "Por favor, escribe tu feedback a continuación:"
                    
                elif 'audio' in message_text.lower():
                    feedback_type = 'AUDIO'
                    self._save_session_data({
                        **self.session_data,
                        'feedback_type': 'AUDIO'
                    })
                    return "Por favor, adjunta tu archivo de audio o utiliza el botón de grabación."
                
                # Handle the actual feedback submission (simplified)
                if 'feedback_type' in self.session_data:
                    if self.session_data['feedback_type'] == 'TEXT':
                        try:
                            visit = Visit.objects.get(id=visit_id)
                            Feedback.objects.create(
                                visit=visit,
                                feedback_type='TEXT',
                                feedback_text=message_text
                            )
                            
                            self._save_session_state(self.SESSION_STATES['READY_FOR_REPORT'])
                            return "¡Gracias por tu feedback! ¿Deseas generar un informe de esta visita ahora?"
                        except Visit.DoesNotExist:
                            return "Lo siento, no se encontró la visita. Por favor, intenta de nuevo."
            
            # Handle ready for report
            elif self.session_state == self.SESSION_STATES['READY_FOR_REPORT']:
                # Check for confirmation to generate report
                if any(word in message_text.lower() for word in ['si', 'sí', 'generar', 'continue', 'ok']):
                    # Return None to signal that GPT should handle this for report generation
                    logger.info("User confirmed report generation, delegating to GPT")
                    return "__USE_GPT__"
                else:
                    return "Entiendo que no deseas generar un informe ahora. ¿En qué más puedo ayudarte?"
            
            # If we reach here and didn't handle it with any specific logic, return the default response
            logger.info(f"No specific handler for intent {intent}, using default response")
            return self.DEFAULT_RESPONSES['unknown']
            
        except Exception as e:
            logger.error(f"Error in SmartResponseEngine.process_message: {str(e)}")
            return self.DEFAULT_RESPONSES['error']

class ChatProcessor:
    """
    Centralized service for processing chat messages from any source
    (web UI, WhatsApp, or other channels)
    """
    
    def __init__(self):
        self.chatgpt_service = ChatGPTService()
        
    def build_message_context(self, conversation: Conversation) -> Dict:
        """
        Build context for message processing, including conversation history
        and relevant data about the conversation participants
        """
        context = {}
        
        # Add delegate information if available
        if conversation.delegate:
            context['delegate'] = {
                'name': conversation.delegate.name,
                'code': conversation.delegate.code
            }
        
        # Add conversation history (last 5 messages)
        recent_messages = Message.objects.filter(
            conversation=conversation
        ).exclude(
            content__startswith="__STATE__:"  # Exclude internal state management messages
        ).exclude(
            content__startswith="__DATA__:"   # Exclude internal data management messages
        ).order_by('-timestamp')[:5].values('content', 'direction')
        
        if recent_messages:
            context['history'] = list(reversed(list(recent_messages)))
            
        # Add channel information
        channel = self._determine_channel(conversation)
        context['channel'] = channel
        
        # Add channel-specific context
        if channel == 'whatsapp':
            # For WhatsApp messages, add any relevant WhatsApp-specific context
            context['message_format'] = 'whatsapp'
        
        return context
    
    def _determine_channel(self, conversation: Conversation) -> str:
        """
        Determine the channel type for this conversation
        """
        # WhatsApp conversations typically have a valid phone number starting with +
        if conversation.client_phone and (conversation.client_phone.startswith('+') or 
                                          conversation.client_phone.startswith('whatsapp:')):
            return 'whatsapp'
        
        # Web chat conversations have a special format or delegate prefix
        if conversation.client_phone and conversation.client_phone.startswith('delegado_'):
            return 'webchat'
            
        # Default fallback
        return 'unknown'
    
    def process_message(self, message_obj: Message) -> Tuple[bool, Optional[str]]:
        """
        Process a message and generate a response using the following sequence:
        1. Try QAService to match against known questions
        2. Try SmartResponseEngine for procedural responses
        3. Fall back to AI for complex queries
        
        Returns a tuple of (success, response_text)
        """
        try:
            # First try to match with our Q&A database
            qa_service = QAService(delegate=message_obj.conversation.delegate)
            qa_result = qa_service.process_query(message_obj.content, message_obj.conversation)
            
            if qa_result['success']:
                # We found a matching question and answer
                logger.info(f"Found matching Q&A with confidence {qa_result['confidence']}")
                
                # Update original message to mark as processed
                message_obj.ai_processed = True
                message_obj.ai_response = qa_result['response']
                message_obj.save()
                
                return True, qa_result['response']
            
            # If no Q&A match, try our SmartResponseEngine
            smart_engine = SmartResponseEngine(message_obj.conversation)
            smart_response = smart_engine.process_message(message_obj.content)
            
            if smart_response and smart_response != "__USE_GPT__":
                # We got a direct response from the backend, use it
                logger.info("Generated backend response without using GPT")
                
                # Update original message to mark as processed
                message_obj.ai_processed = True
                message_obj.ai_response = smart_response
                message_obj.save()
                
                return True, smart_response
            
            # If no matches yet, fallback to GPT
            logger.info("No backend or Q&A response, falling back to GPT")
            
            # Build context for the AI
            context = self.build_message_context(message_obj.conversation)
            
            # Add any session data from SmartResponseEngine to enhance GPT context
            if hasattr(smart_engine, 'session_data') and smart_engine.session_data:
                if 'selected_pharmacy' in smart_engine.session_data:
                    pharmacy = smart_engine.session_data['selected_pharmacy']
                    context['pharmacy'] = {
                        'name': pharmacy.get('name', ''),
                        'address': pharmacy.get('address', ''),
                        'last_visit': pharmacy.get('last_visit_date', 'Sin visitas previas')
                    }
                
                if 'visits' in smart_engine.session_data:
                    context['visits'] = [
                        {'date': v['date'], 'status': v['status']}
                        for v in smart_engine.session_data['visits']
                    ]
            
            # Process with AI
            response = self.chatgpt_service.process_message(
                message_obj.content, 
                context=context
            )
            
            # Update original message to mark as processed
            message_obj.ai_processed = True
            message_obj.ai_response = response
            message_obj.save()
            
            return True, response
            
        except Exception as e:
            logger.error(f"Error in ChatProcessor.process_message: {str(e)}")
            logger.error(traceback.format_exc())
            return False, f"Error procesando el mensaje: {str(e)}"
    
    def create_response_message(self, conversation: Conversation, content: str) -> Message:
        """
        Create a response message in the conversation
        """
        return Message.objects.create(
            conversation=conversation,
            content=content,
            direction='OUT',
            ai_processed=True
        )
    
    def handle_incoming_message(self, message_content: str, conversation: Conversation, 
                               source: str = 'webchat') -> Tuple[Message, Message]:
        """
        Handle an incoming message from any source:
        1. Create an incoming message
        2. Create a placeholder for the response
        3. Process the message in the background (the task will update the placeholder)
        
        Args:
            message_content: The text content of the message
            conversation: The conversation this message belongs to
            source: Source of the message ('webchat', 'whatsapp', 'api', etc.)
            
        Returns: (user_message, placeholder_message)
        """
        # Log the incoming message source
        logger.info(f"Handling incoming message from source: {source}")
        
        # Create user message
        user_message = Message.objects.create(
            conversation=conversation,
            content=message_content,
            direction='IN'
        )
        
        # Create placeholder for AI response
        placeholder = Message.objects.create(
            conversation=conversation,
            content="Procesando respuesta...",
            direction='OUT'
        )
        
        # Store the source as metadata on the message
        # This allows different processing strategies based on source
        InteractionLog.objects.create(
            message=user_message,
            ai_response=f"Source: {source}"
        )
        
        return user_message, placeholder
    
    def prepare_message_for_whatsapp(self, content: str) -> str:
        """
        Prepare a message to be sent via WhatsApp
        - Format text appropriately for WhatsApp
        - Handle length limits and other constraints
        """
        # Basic WhatsApp formatting
        # Max length for WhatsApp is around 4096 chars
        if len(content) > 4000:
            content = content[:3997] + "..."
            
        # Ensure proper formatting for WhatsApp
        # Replace multiple newlines with just two
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # Convert markdown style formatting to WhatsApp formatting
        # WhatsApp uses *bold*, _italic_, and ~strikethrough~
        content = re.sub(r'\*\*(.*?)\*\*', r'*\1*', content)  # Convert **bold** to *bold*
        content = re.sub(r'__(.*?)__', r'_\1_', content)      # Convert __italic__ to _italic_
        
        return content

class QAService:
    """
    Service for handling question matching and answer retrieval from the database.
    """
    MATCH_THRESHOLD = 0.6  # Minimum similarity score to consider a match

    def __init__(self, delegate=None):
        self.delegate = delegate
    
    def find_matching_question(self, user_query: str) -> Tuple[Optional[Question], float]:
        """
        Find the best matching question in the database for a given user query.
        Returns the question object and the confidence score.
        """
        if not user_query or len(user_query.strip()) < 3:
            return None, 0.0
            
        # Clean and normalize the query
        user_query = self._normalize_text(user_query)
        
        # First try keyword matching
        questions_by_keywords = self._match_by_keywords(user_query)
        if questions_by_keywords:
            # Sort by similarity score
            questions_by_keywords.sort(key=lambda x: x[1], reverse=True)
            if questions_by_keywords[0][1] >= self.MATCH_THRESHOLD:
                return questions_by_keywords[0]
        
        # If no good keyword matches, try full text similarity
        questions_by_similarity = self._match_by_similarity(user_query)
        if questions_by_similarity:
            # Sort by similarity score
            questions_by_similarity.sort(key=lambda x: x[1], reverse=True)
            if questions_by_similarity[0][1] >= self.MATCH_THRESHOLD:
                return questions_by_similarity[0]
                
        return None, 0.0
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text by removing extra spaces and converting to lowercase"""
        return ' '.join(text.lower().split())
    
    def _match_by_keywords(self, query: str) -> List[Tuple[Question, float]]:
        """Match query against question keywords"""
        results = []
        questions = Question.objects.filter(is_active=True)
        
        for question in questions:
            if not question.keywords:
                continue
                
            keywords = [k.strip().lower() for k in question.keywords.split(',')]
            max_score = 0
            
            for keyword in keywords:
                if keyword in query:
                    # Calculate a match score based on keyword coverage
                    score = len(keyword) / len(query) if len(query) > 0 else 0
                    max_score = max(max_score, score)
            
            if max_score > 0:
                results.append((question, max_score))
                
        return results
    
    def _match_by_similarity(self, query: str) -> List[Tuple[Question, float]]:
        """Match query against question text using similarity algorithm"""
        results = []
        questions = Question.objects.filter(is_active=True)
        
        for question in questions:
            question_text = self._normalize_text(question.text)
            similarity = SequenceMatcher(None, query, question_text).ratio()
            if similarity > 0:
                results.append((question, similarity))
                
        return results
    
    def get_answer(self, question: Question) -> Optional[str]:
        """Get the best answer for a given question"""
        # First try to get the default answer
        try:
            default_answer = question.answers.get(is_default=True)
            return default_answer.text
        except Answer.DoesNotExist:
            # If no default answer, get the first one
            answer = question.answers.first()
            if answer:
                return answer.text
        
        return None
    
    def process_query(self, user_query: str, conversation: Conversation) -> Dict[str, Any]:
        """
        Process a user query, find matching questions and answers, and log the interaction.
        Returns a dictionary with the response and match information.
        """
        # Find matching question
        matched_question, confidence = self.find_matching_question(user_query)
        
        result = {
            'success': False,
            'response': None,
            'confidence': confidence,
            'question_id': None,
            'answer_id': None
        }
        
        if not matched_question or confidence < self.MATCH_THRESHOLD:
            return result
            
        # Get answer for the matched question
        answer_text = self.get_answer(matched_question)
        if not answer_text:
            return result
            
        # Get the answer object
        try:
            answer = matched_question.answers.filter(text=answer_text).first()
        except Answer.DoesNotExist:
            return result
            
        # Log the interaction
        interaction = QAInteraction.objects.create(
            user_query=user_query,
            matched_question=matched_question,
            provided_answer=answer,
            conversation=conversation,
            delegate=self.delegate,
            success_rate=confidence
        )
        
        # Return the result
        result.update({
            'success': True,
            'response': answer_text,
            'question_id': matched_question.id,
            'answer_id': answer.id if answer else None
        })
        
        return result
