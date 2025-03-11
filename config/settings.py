import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = 'django-insecure-your-secret-key-here'

DEBUG = True

ALLOWED_HOSTS = []

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'oauth2_provider',
    'rest_framework',
    'apps.agents',
    'apps.chat',
    'apps.whatsapp',
    'apps.dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates", BASE_DIR / "apps/dashboard/templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'delegados_db',
        'USER': 'postgres',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'es-es'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Celery Configuration
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# OAuth2 Configuration
OAUTH2_PROVIDER = {
    'SCOPES': {
        'read': 'Read scope',
        'write': 'Write scope',
    }
}

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': [],
}

# OpenAI Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', 'tu-clave-api-de-openai')  # Reemplaza con tu clave API real
OPENAI_CONFIG = {
    'model': 'gpt-3.5-turbo',
    'temperature': 0.7,
    'max_tokens': 500,
    'system_prompt': """Eres un asistente especializado de DermoFarm que ayuda a responder 
    consultas sobre productos dermatológicos. Debes ser profesional, preciso y amable. 
    Bases tu conocimiento en información verificada sobre productos dermatológicos y 
    siempre recomiendas consultar con un profesional de la salud para casos específicos."""
}

# WhatsApp Configuratio
# Nuevas configuraciones para webhooks genéricos de WhatsApp
WHATSAPP_API_URL = os.getenv('https://graph.facebook.com/v22.0/571448366056438/messages')  # URL base de la API de WhatsApp
WHATSAPP_API_TOKEN = os.getenv('EAA5aL45muV4BO1ShCCedkzeHBX3CaGeo8pPWblqhENW859WEZCCr6h8tua7vyd2iM9Sqo05g7Jj2I7SZAmIaZBm2ZCu5BQvP1tZAFAbSmMTgZCsuP2IxYouHr00yYUIB4dwmZCkcY910kGDBhvo3JVER6apZAlWZBSv2jamN7pZAUkjRxrZBclULU7OIiHqmZAkG6pYgt4ICzlc7aAUda3GqzeefMvZC0igZDZD')  # Token de acceso de la API
WHATSAPP_PHONE_ID = os.getenv('571448366056438')  # ID del número de teléfono de WhatsApp
WHATSAPP_PHONE_NUMBER = os.getenv('+1 555 635 3488')  # Número de teléfono de WhatsApp
WHATSAPP_WEBHOOK_SECRET = os.getenv('WHATSAPP_WEBHOOK_SECRET', '')  # Secreto para verificar las firmas de los webhooks
WHATSAPP_WEBHOOK_VERIFY_TOKEN = os.getenv('WHATSAPP_WEBHOOK_VERIFY_TOKEN', 'tu-token-de-verificacion')  # Token para verificar la configuración del webhook