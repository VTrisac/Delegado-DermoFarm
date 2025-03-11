from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import agents_view
from . import views

router = DefaultRouter()
router.register(r'profiles', views.AgentProfileViewSet)

urlpatterns = [
    path('', agents_view, name="agents"),
    path('api/', include(router.urls)),
]
