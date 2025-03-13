from django.db import models
from django.utils import timezone
from django.conf import settings

class TimestampedModel(models.Model):
    """Abstract base model with created and updated timestamps."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class Delegate(TimestampedModel):
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    terms_accepted = models.BooleanField(default=False)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['code', 'name']),
            models.Index(fields=['terms_accepted', '-last_login_at'])
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"

class Conversation(TimestampedModel):
    agent = models.ForeignKey('agents.AgentProfile', on_delete=models.SET_NULL, null=True)
    client_phone = models.CharField(max_length=50, db_index=True)
    is_active = models.BooleanField(default=True)
    delegate = models.ForeignKey(Delegate, on_delete=models.SET_NULL, null=True, related_name='conversations')
    thread_id = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['client_phone', 'is_active']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['delegate', '-updated_at'])
        ]
        ordering = ['-updated_at']

    def __str__(self):
        return f"Conv: {self.client_phone} ({self.id})"

class Message(TimestampedModel):
    DIRECTION_CHOICES = [
        ('IN', 'Incoming'),
        ('OUT', 'Outgoing'),
    ]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    content = models.TextField()
    direction = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    ai_processed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['conversation', '-timestamp']),
            models.Index(fields=['direction', 'ai_processed'])
        ]
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.direction} - {self.content[:50]}"

class QuestionCategory(TimestampedModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='subcategories')

    class Meta:
        verbose_name_plural = "Question Categories"
        ordering = ['name']

    def __str__(self):
        return self.name

class Question(TimestampedModel):
    text = models.TextField()
    category = models.ForeignKey(QuestionCategory, on_delete=models.SET_NULL, null=True, related_name='questions')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    keywords = models.TextField(blank=True, help_text="Comma-separated keywords for better matching")

    class Meta:
        indexes = [
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['-created_at'])
        ]

    def __str__(self):
        return self.text[:100]

class Answer(TimestampedModel):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='answers')
    content = models.TextField()
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['question', 'is_default'])
        ]

    def __str__(self):
        return f"Answer to: {self.question.text[:50]}"

class QAInteraction(TimestampedModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    user_query = models.TextField()
    matched_question = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True)
    provided_answer = models.ForeignKey(Answer, on_delete=models.SET_NULL, null=True)
    success_rate = models.FloatField(default=0.0)
    feedback = models.TextField(blank=True)
    response_time = models.FloatField(help_text="Response time in seconds", null=True)

    class Meta:
        indexes = [
            models.Index(fields=['conversation', '-created_at']),
            models.Index(fields=['success_rate'])
        ]

    def __str__(self):
        return f"Q&A: {self.user_query[:50]}"

class Pharmacy(TimestampedModel):
    name = models.CharField(max_length=255)
    address = models.TextField()
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    revenue = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    location = models.CharField(max_length=255, blank=True)
    region = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Pharmacies"
        indexes = [
            models.Index(fields=['name', 'is_active']),
            models.Index(fields=['region', 'is_active']),
            models.Index(fields=['location'])
        ]
        ordering = ['name']

    def __str__(self):
        return self.name

class Visit(TimestampedModel):
    STATUS_CHOICES = [
        ('PENDING', 'Pendiente'),
        ('IN_PROGRESS', 'En Progreso'),
        ('COMPLETED', 'Completada'),
        ('CANCELLED', 'Cancelada'),
    ]

    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE, related_name='visits')
    delegate = models.ForeignKey(Delegate, on_delete=models.CASCADE, related_name='visits')
    visit_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    notes = models.TextField(blank=True)
    next_visit_date = models.DateTimeField(null=True, blank=True)
    next_visit_reminder = models.TextField(blank=True)
    summary_confirmed = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=['pharmacy', '-visit_date']),
            models.Index(fields=['delegate', '-visit_date']),
            models.Index(fields=['status', '-visit_date']),
            models.Index(fields=['-next_visit_date'])
        ]
        ordering = ['-visit_date']

    def __str__(self):
        return f"Visit to {self.pharmacy.name} on {self.visit_date}"

class Feedback(TimestampedModel):
    FEEDBACK_TYPES = [
        ('TEXT', 'Text'),
        ('AUDIO', 'Audio'),
    ]

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='feedbacks')
    feedback_type = models.CharField(max_length=5, choices=FEEDBACK_TYPES)
    feedback_text = models.TextField(blank=True)
    audio_file = models.FileField(upload_to='feedback_audio/', null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['visit', '-created_at'])
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"Feedback for visit {self.visit.id}"
