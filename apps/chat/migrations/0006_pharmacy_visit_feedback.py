# Generated by Django 4.2.7 on 2025-03-07 11:09

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0005_delegate_conversation_delegate'),
    ]

    operations = [
        migrations.CreateModel(
            name='Pharmacy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('address', models.TextField()),
                ('phone', models.CharField(blank=True, max_length=20, null=True)),
                ('email', models.EmailField(blank=True, max_length=254, null=True)),
                ('revenue', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ('last_visit', models.DateTimeField(blank=True, null=True)),
                ('notes', models.TextField(blank=True, null=True)),
            ],
            options={
                'verbose_name_plural': 'Pharmacies',
            },
        ),
        migrations.CreateModel(
            name='Visit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('visit_date', models.DateTimeField(auto_now_add=True)),
                ('status', models.CharField(choices=[('PENDING', 'Pendiente'), ('COMPLETED', 'Completada'), ('CANCELLED', 'Cancelada')], default='PENDING', max_length=20)),
                ('notes', models.TextField(blank=True, null=True)),
                ('next_visit_reminder', models.TextField(blank=True, null=True)),
                ('next_visit_date', models.DateTimeField(blank=True, null=True)),
                ('summary_confirmed', models.BooleanField(default=False)),
                ('delegate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='chat.delegate')),
                ('pharmacy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='chat.pharmacy')),
            ],
        ),
        migrations.CreateModel(
            name='Feedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('feedback_type', models.CharField(choices=[('TEXT', 'Texto'), ('AUDIO', 'Audio')], max_length=5)),
                ('feedback_text', models.TextField(blank=True, null=True)),
                ('audio_file', models.FileField(blank=True, null=True, upload_to='feedback_audio/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('visit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feedbacks', to='chat.visit')),
            ],
        ),
    ]
