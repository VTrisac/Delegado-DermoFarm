# Guía para Desarrolladores - Delegado

## Configuración del Entorno de Desarrollo

1. **Requisitos Previos**
```bash
Python 3.9+
PostgreSQL 13+
Redis Server
```

2. **Configuración del Entorno Virtual**
```bash
python -m venv venv
source venv/bin/activate  # En Unix
venv\Scripts\activate     # En Windows
pip install -r requirements.txt
```

3. **Variables de Entorno**
Crear archivo `.env` en la raíz:
```
DATABASE_URL=postgresql://user:password@localhost:5432/delegados_db
REDIS_URL=redis://localhost:6379/0
WHATSAPP_API_URL=https://graph.facebook.com/v22.0/YOUR_PHONE_NUMBER_ID/messages
WHATSAPP_TOKEN=your_whatsapp_token
OPENAI_API_KEY=your_openai_api_key
```

## Estructura de Código

### Convenciones de Código

1. **Modelos**
- Un modelo por archivo si es complejo
- Usar managers para lógica de consulta compleja
- Documentar campos importantes

2. **Vistas**
- Usar CBV (Class-Based Views) para operaciones CRUD
- APIView para endpoints de API
- Decoradores para control de permisos

3. **Servicios**
- Lógica de negocio en clases de servicio
- Inyección de dependencias cuando sea posible
- Manejo de errores consistente

### Patrones de Diseño Utilizados

1. **Repository Pattern**
- Abstracción de la capa de datos
- Managers de Django como repositorios

2. **Service Layer**
- Lógica de negocio en servicios
- Separación de responsabilidades
- Reutilización de código

3. **Factory Pattern**
- Creación de objetos complejos
- Manejo de diferentes tipos de mensajes

## Flujos de Trabajo

### 1. Procesamiento de Mensajes
```
Cliente -> Webhook -> WhatsAppMessage -> Celery Task -> Procesamiento -> Respuesta
```

### 2. Sistema de Chat Interno
```
Delegado -> API -> Message -> Queue -> Procesamiento -> Notificación
```

### 3. Visitas y Feedback
```
Delegado -> Visita -> Procesamiento GPT -> Reporte -> Confirmación
```

## Guías de Testing

1. **Tests Unitarios**
- Un test por funcionalidad
- Usar fixtures para datos de prueba
- Mockear servicios externos

2. **Tests de Integración**
- Probar flujos completos
- Verificar interacciones entre componentes
- Simular condiciones reales

3. **Tests de API**
- Usar APITestCase
- Verificar respuestas y códigos HTTP
- Probar autenticación y permisos

## Despliegue

1. **Preparación**
```bash
python manage.py check --deploy
python manage.py collectstatic
python manage.py migrate
```

2. **Servicios Requeridos**
- Servidor Web (Nginx/Apache)
- Gunicorn/uWSGI
- Supervisor para Celery
- Redis para colas

## Monitoreo

1. **Logs**
- Usar logging estructurado
- Niveles de log apropiados
- Rotación de logs

2. **Métricas**
- Monitoreo de workers Celery
- Tiempos de respuesta API
- Uso de recursos

3. **Alertas**
- Configurar alertas críticas
- Monitorear errores 5xx
- Supervisar colas de mensajes