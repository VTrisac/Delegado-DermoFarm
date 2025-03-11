from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from .models import AgentProfile
from .serializers import AgentProfileSerializer
from django.shortcuts import render
from django.contrib.auth.decorators import login_required

class AgentProfileViewSet(viewsets.ModelViewSet):
    queryset = AgentProfile.objects.all()
    serializer_class = AgentProfileSerializer
    permission_classes = [IsAuthenticated]

@login_required
def agents_view(request):
    agents = AgentProfile.objects.all()
    return render(request, "agents/agents.html", {"agents": agents})