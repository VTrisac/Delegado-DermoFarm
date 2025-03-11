# Generated by Django 4.2.7 on 2025-03-06 15:05

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0002_pharmacy_visit_feedback'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='visit',
            name='agent',
        ),
        migrations.RemoveField(
            model_name='visit',
            name='pharmacy',
        ),
        migrations.AddField(
            model_name='message',
            name='ai_processed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='message',
            name='ai_response',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.DeleteModel(
            name='Feedback',
        ),
        migrations.DeleteModel(
            name='Pharmacy',
        ),
        migrations.DeleteModel(
            name='Visit',
        ),
    ]
