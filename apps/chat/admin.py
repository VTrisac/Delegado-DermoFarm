from django.contrib import admin
from .models import (
    Conversation, Message, Pharmacy, 
    Visit, Feedback, Delegate, QuestionCategory, 
    Question, Answer, QAInteraction
)

class AnswerInline(admin.TabularInline):
    model = Answer
    extra = 1

@admin.register(QuestionCategory)
class QuestionCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_at')
    search_fields = ('name', 'description')

@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'category', 'is_active', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('text', 'keywords')
    inlines = [AnswerInline]

@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = ('question', 'content', 'is_default')
    list_filter = ('is_default',)
    search_fields = ('content',)
    raw_id_fields = ('question',)

@admin.register(QAInteraction)
class QAInteractionAdmin(admin.ModelAdmin):
    list_display = ('user_query', 'matched_question', 'success_rate', 'created_at')
    list_filter = ('success_rate',)
    search_fields = ('user_query',)
    date_hierarchy = 'created_at'
    raw_id_fields = ('matched_question', 'provided_answer', 'conversation')

# Register other existing models
admin.site.register(Conversation)
admin.site.register(Message)
admin.site.register(Pharmacy)
admin.site.register(Visit)
admin.site.register(Feedback)
admin.site.register(Delegate)