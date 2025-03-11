# Delegado - Sistema de Gestión para Delegados DermoFarm

Sistema web para la gestión de comunicaciones entre delegados de DermoFarm y sus clientes a través de WhatsApp y chat interno.

## Estructura del Proyecto

```
delegado/
├── apps/                     # Directorio principal de aplicaciones
│   ├── agents/              # Gestión de agentes y perfiles
│   ├── chat/                # Sistema de mensajería interna
│   ├── dashboard/           # Panel de administración y métricas
│   └── whatsapp/           # Integración con WhatsApp
├── config/                  # Configuración del proyecto
├── static/                  # Archivos estáticos
├── templates/               # Plantillas base
└── manage.py               # Script de gestión de Django
```

## Aplicaciones Principales

### 1. agents/
- Gestión de perfiles de agentes
- Autenticación y autorización
- Seguimiento de actividad de agentes

### 2. chat/
- Sistema de mensajería interna
- Gestión de conversaciones
- Integración con IA para procesamiento de mensajes
- Sistema de Q&A para respuestas automáticas
- Gestión de farmacias y visitas

### 3. dashboard/
- Panel de administración
- Visualización de métricas
- Reportes y estadísticas

### 4. whatsapp/
- Integración con API de WhatsApp
- Gestión de mensajes y estados
- Logs de interacciones
- Webhooks para comunicación bidireccional

## Tecnologías Principales

- Django 4.2.7
- PostgreSQL
- Celery + Redis
- OAuth2 para autenticación
- Django REST Framework
- Integración con WhatsApp Business API

## Modelos de Datos Principales

### Agentes
- AgentProfile: Perfil de agentes con datos de contacto y estado

### Chat
- Conversation: Gestión de conversaciones
- Message: Mensajes de chat
- Delegate: Información de delegados
- Pharmacy: Datos de farmacias
- Visit: Registro de visitas a farmacias
- QA Models: Sistema de preguntas y respuestas

### WhatsApp
- WhatsAppMessage: Registro de mensajes de WhatsApp
- WhatsAppLog: Logs de eventos y estados

## Arquitectura

El proyecto sigue una arquitectura modular basada en Django, con las siguientes características:

1. **Separación de Responsabilidades**
   - Cada app maneja un dominio específico
   - Modelos bien definidos por dominio
   - Vistas organizadas por funcionalidad

2. **Procesamiento Asíncrono**
   - Celery para tareas en segundo plano
   - Redis como message broker
   - Procesamiento de mensajes WhatsApp asíncrono

3. **API REST**
   - Endpoints documentados
   - Autenticación OAuth2
   - Serializers para cada modelo principal

4. **Seguridad**
   - Autenticación obligatoria
   - Manejo de permisos por rol
   - Validación de webhooks WhatsApp