from django.db import models
from django.contrib.auth.models import User
from apps.agents.models import AgentProfile

class Delegate(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    terms_accepted = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Delegado: {self.name} ({self.code})"

class Conversation(models.Model):
    agent = models.ForeignKey(AgentProfile, on_delete=models.CASCADE)
    client_phone = models.CharField(max_length=15, db_index=True)
    delegate = models.ForeignKey(Delegate, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    thread_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Conversación: {self.agent.user.username} - {self.client_phone}"

class Message(models.Model):
    DIRECTION_CHOICES = [
        ('IN', 'Entrante'),
        ('OUT', 'Saliente'),
    ]
    
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    content = models.TextField()
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    attachment = models.FileField(upload_to='attachments/', null=True, blank=True)
    ai_processed = models.BooleanField(default=False)
    ai_response = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Mensaje ({self.direction}): {self.content[:20]}"

class InteractionLog(models.Model):
    agent = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    message = models.OneToOneField("chat.Message", on_delete=models.CASCADE)  # Importación diferida para evitar circular import
    ai_response = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Log de {self.agent} - {self.created_at}"

class Pharmacy(models.Model):
    name = models.CharField(max_length=255, unique=True)
    address = models.TextField()
    phone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    revenue = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    last_visit = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.name} - {self.address}"
    
    class Meta:
        verbose_name_plural = "Pharmacies"

class Visit(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pendiente'),
        ('COMPLETED', 'Completada'),
        ('CANCELLED', 'Cancelada'),
    ]
    
    delegate = models.ForeignKey(Delegate, on_delete=models.CASCADE)
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE)
    visit_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    notes = models.TextField(blank=True, null=True)
    next_visit_reminder = models.TextField(blank=True, null=True)
    next_visit_date = models.DateTimeField(blank=True, null=True)
    summary_confirmed = models.BooleanField(default=False)
    
    def __str__(self):
        return f"Visita a {self.pharmacy.name} por {self.delegate.name}"

class Feedback(models.Model):
    FEEDBACK_TYPES = [
        ('TEXT', 'Texto'),
        ('AUDIO', 'Audio'),
    ]
    
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='feedbacks')
    feedback_type = models.CharField(max_length=5, choices=FEEDBACK_TYPES)
    feedback_text = models.TextField(blank=True, null=True)
    audio_file = models.FileField(upload_to='feedback_audio/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Feedback de visita {self.visit.id} - {self.get_feedback_type_display()}"

# New models for Q&A functionality
class QuestionCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Question Categories"

class Question(models.Model):
    text = models.TextField()
    keywords = models.TextField(blank=True, null=True, help_text="Comma-separated keywords to match this question")
    category = models.ForeignKey(QuestionCategory, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.text[:50]

class Answer(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    text = models.TextField()
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.text[:50]
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['question'],
                condition=models.Q(is_default=True),
                name='unique_default_answer_per_question'
            )
        ]

class QAInteraction(models.Model):
    user_query = models.TextField()
    matched_question = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True, blank=True)
    provided_answer = models.ForeignKey(Answer, on_delete=models.SET_NULL, null=True, blank=True)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    delegate = models.ForeignKey(Delegate, on_delete=models.SET_NULL, null=True, blank=True)
    success_rate = models.FloatField(default=0.0, help_text="Match confidence score (0-1)")
    created_at = models.DateTimeField(auto_now_add=True)
    feedback = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"Query: {self.user_query[:30]}"
