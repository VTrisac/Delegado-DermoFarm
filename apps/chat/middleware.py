import time
import logging
from typing import Optional
from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

class RequestTimingMiddleware(MiddlewareMixin):
    """
    Middleware to track request timing and log slow requests.
    Also handles request rate limiting and caching headers.
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.get_response = get_response
        self.slow_request_threshold = getattr(settings, 'SLOW_REQUEST_THRESHOLD', 1.0)  # seconds
        self.rate_limit_threshold = getattr(settings, 'RATE_LIMIT_THRESHOLD', 100)  # requests per minute
        
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Handle incoming request processing."""
        # Start timing
        request.start_time = time.time()
        
        # Rate limiting check for API endpoints
        if self._is_api_request(request):
            client_ip = self._get_client_ip(request)
            if not self._check_rate_limit(client_ip):
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return HttpResponse("Rate limit exceeded", status=429)
        
        # Check cache for GET requests
        if request.method == "GET" and self._is_cacheable(request):
            cache_key = self._get_cache_key(request)
            cached_response = cache.get(cache_key)
            if cached_response:
                return cached_response
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Handle response processing and logging."""
        if not hasattr(request, 'start_time'):
            return response
            
        # Calculate request duration
        duration = time.time() - request.start_time
        
        # Log slow requests
        if duration > self.slow_request_threshold:
            logger.warning(
                f"Slow request detected: {request.method} {request.path} "
                f"({duration:.2f}s)"
            )
        
        # Add timing header for monitoring
        response['X-Request-Time'] = str(duration)
        
        # Cache successful GET responses
        if (request.method == "GET" and 
            response.status_code == 200 and 
            self._is_cacheable(request)):
            cache_key = self._get_cache_key(request)
            cache.set(cache_key, response, timeout=300)  # Cache for 5 minutes
        
        # Add cache control headers
        if self._is_api_request(request):
            response['Cache-Control'] = 'private, max-age=0, no-cache'
        elif self._is_static_request(request):
            response['Cache-Control'] = 'public, max-age=31536000'  # 1 year
        
        return response
    
    def _is_api_request(self, request: HttpRequest) -> bool:
        """Check if request is to an API endpoint."""
        return request.path.startswith('/api/') or 'application/json' in request.headers.get('Accept', '')
    
    def _is_static_request(self, request: HttpRequest) -> bool:
        """Check if request is for static files."""
        return request.path.startswith(('/static/', '/media/'))
    
    def _is_cacheable(self, request: HttpRequest) -> bool:
        """Check if request can be cached."""
        return (not request.path.startswith('/admin/') and 
                not request.path.startswith('/api/') and
                not request.path.startswith('/chat/messages/') and
                'sessionid' not in request.COOKIES)
    
    def _get_cache_key(self, request: HttpRequest) -> str:
        """Generate cache key for request."""
        return f"view_cache_{request.path}_{hash(frozenset(request.GET.items()))}"
    
    def _get_client_ip(self, request: HttpRequest) -> str:
        """Get client IP from request, handling proxies."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')
    
    def _check_rate_limit(self, client_ip: str) -> bool:
        """Check if client has exceeded rate limit."""
        cache_key = f'rate_limit_{client_ip}'
        request_count = cache.get(cache_key, 0)
        
        if request_count >= self.rate_limit_threshold:
            return False
            
        # Increment counter with 1-minute expiry
        cache.set(cache_key, request_count + 1, timeout=60)
        return True

class ConversationMiddleware(MiddlewareMixin):
    """
    Middleware to handle conversation context and session management.
    Also tracks conversation metrics and handles cleanup.
    """
    
    def process_request(self, request: HttpRequest) -> Optional[HttpResponse]:
        """Add conversation context to request if available."""
        if not hasattr(request, 'conversation_id'):
            conversation_id = request.GET.get('conversation_id')
            if conversation_id:
                try:
                    from apps.chat.models import Conversation
                    conversation = Conversation.objects.select_related(
                        'delegate'
                    ).get(id=conversation_id)
                    request.conversation = conversation
                except Conversation.DoesNotExist:
                    pass
    
    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Handle conversation metrics and cleanup."""
        if hasattr(request, 'conversation'):
            # Update last activity timestamp
            request.conversation.save()  # This updates updated_at
            
            # Track conversation metrics
            self._update_conversation_metrics(request.conversation)
            
            # Clean up old conversations if needed
            self._cleanup_old_conversations()
        
        return response
    
    def _update_conversation_metrics(self, conversation) -> None:
        """Update conversation activity metrics."""
        cache_key = f'conv_metrics_{conversation.id}'
        metrics = cache.get(cache_key, {})
        
        # Update metrics
        metrics['last_activity'] = time.time()
        metrics['request_count'] = metrics.get('request_count', 0) + 1
        
        cache.set(cache_key, metrics, timeout=3600)  # 1 hour
    
    def _cleanup_old_conversations(self) -> None:
        """
        Clean up old inactive conversations.
        Run this with a low probability to avoid doing it too often.
        """
        if time.time() % 100 < 1:  # ~1% chance of running
            from django.utils import timezone
            from datetime import timedelta
            from apps.chat.models import Conversation
            
            # Mark conversations inactive if no activity for 24 hours
            cutoff = timezone.now() - timedelta(hours=24)
            Conversation.objects.filter(
                is_active=True,
                updated_at__lt=cutoff
            ).update(is_active=False)