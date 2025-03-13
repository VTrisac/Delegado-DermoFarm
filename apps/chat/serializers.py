from rest_framework import serializers
from django.core.cache import cache
from .models import (
    Conversation, Message, Delegate, Question, 
    Answer, QAInteraction, QuestionCategory
)

class DelegateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Delegate
        fields = ['id', 'code', 'name', 'terms_accepted', 'terms_accepted_at']
        read_only_fields = ['terms_accepted_at']

    def validate_code(self, value):
        """Ensure delegate code is unique and properly formatted."""
        if not value.isalnum():
            raise serializers.ValidationError("Delegate code must be alphanumeric")
        return value.upper()

class ConversationSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Conversation
        fields = ['id', 'client_phone', 'is_active', 'created_at', 'updated_at', 
                 'last_message', 'unread_count', 'thread_id']
        read_only_fields = ['created_at', 'updated_at']

    def get_last_message(self, obj):
        """Get cached or fetch last message for conversation."""
        cache_key = f'conv_last_msg_{obj.id}'
        cached_msg = cache.get(cache_key)
        
        if cached_msg:
            return cached_msg
            
        message = obj.messages.order_by('-timestamp').first()
        if message:
            data = {
                'content': message.content[:100],
                'timestamp': message.timestamp,
                'direction': message.direction
            }
            cache.set(cache_key, data, timeout=300)  # Cache for 5 minutes
            return data
        return None

    def get_unread_count(self, obj):
        """Get count of unread messages in conversation."""
        cache_key = f'conv_unread_{obj.id}'
        cached_count = cache.get(cache_key)
        
        if cached_count is not None:
            return cached_count
            
        count = obj.messages.filter(
            direction='IN',
            ai_processed=False
        ).count()
        
        cache.set(cache_key, count, timeout=60)  # Cache for 1 minute
        return count

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'conversation', 'content', 'direction', 
                 'timestamp', 'ai_processed']
        read_only_fields = ['timestamp', 'ai_processed']

    def validate_content(self, value):
        """Ensure message content is not empty and within limits."""
        if not value.strip():
            raise serializers.ValidationError("Message content cannot be empty")
        if len(value) > 4096:
            raise serializers.ValidationError("Message too long (max 4096 chars)")
        return value.strip()

class QuestionCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionCategory
        fields = ['id', 'name', 'description', 'parent']

    def validate(self, data):
        """Prevent circular parent references."""
        if 'parent' in data and data['parent']:
            current = data['parent']
            while current:
                if current.id == self.instance.id if self.instance else None:
                    raise serializers.ValidationError("Circular parent reference")
                current = current.parent
        return data

class QuestionSerializer(serializers.ModelSerializer):
    answers = serializers.SerializerMethodField()
    
    class Meta:
        model = Question
        fields = ['id', 'text', 'category', 'is_active', 'keywords', 'answers']
        read_only_fields = ['created_at']

    def get_answers(self, obj):
        """Get cached or fetch answers for question."""
        cache_key = f'question_answers_{obj.id}'
        cached_answers = cache.get(cache_key)
        
        if cached_answers:
            return cached_answers
            
        answers = obj.answers.all()
        data = [{
            'id': answer.id,
            'content': answer.content,
            'is_default': answer.is_default
        } for answer in answers]
        
        cache.set(cache_key, data, timeout=300)  # Cache for 5 minutes
        return data

    def validate_keywords(self, value):
        """Normalize and validate keywords."""
        if not value:
            return ''
        keywords = [k.strip().lower() for k in value.split(',') if k.strip()]
        return ','.join(sorted(set(keywords)))  # Remove duplicates

class AnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Answer
        fields = ['id', 'question', 'content', 'is_default']

    def validate(self, data):
        """Ensure only one default answer per question."""
        if data.get('is_default'):
            if self.instance:
                # If updating an existing answer
                existing = Answer.objects.filter(
                    question=data['question'],
                    is_default=True
                ).exclude(id=self.instance.id)
            else:
                # If creating a new answer
                existing = Answer.objects.filter(
                    question=data['question'],
                    is_default=True
                )
            
            if existing.exists():
                raise serializers.ValidationError(
                    "Question already has a default answer"
                )
        return data

class QAInteractionSerializer(serializers.ModelSerializer):
    matched_question_text = serializers.SerializerMethodField()
    
    class Meta:
        model = QAInteraction
        fields = ['id', 'conversation', 'user_query', 'matched_question',
                 'matched_question_text', 'provided_answer', 'success_rate',
                 'feedback', 'response_time', 'created_at']
        read_only_fields = ['created_at', 'success_rate', 'response_time']

    def get_matched_question_text(self, obj):
        """Get the text of the matched question."""
        if obj.matched_question:
            return obj.matched_question.text
        return None

    def validate_feedback(self, value):
        """Ensure feedback is not too long."""
        if len(value) > 1000:
            raise serializers.ValidationError("Feedback too long (max 1000 chars)")
        return value.strip()