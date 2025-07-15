from rest_framework import serializers
from .models import Prompt

class PromptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prompt
        fields = ['id', 'name', 'prompt', 'version', 'user', 'is_globally_shared']
        read_only_fields = ['user'] # User is set by the view, not directly by the client
