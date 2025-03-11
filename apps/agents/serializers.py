from rest_framework import serializers
from .models import AgentProfile
from django.contrib.auth.models import User

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']

class AgentProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = AgentProfile
        fields = ['id', 'user', 'phone_number', 'is_active', 'created_at', 'updated_at']