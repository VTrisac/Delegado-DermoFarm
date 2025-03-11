from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.views import LogoutView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('dashboard/', include('apps.dashboard.urls')),
    path('chat/', include('apps.chat.urls')),
    path('agents/', include('apps.agents.urls')),
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
]
