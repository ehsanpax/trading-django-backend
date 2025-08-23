from rest_framework import serializers
from .models import UserStudioLayout

class UserStudioLayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserStudioLayout
        fields = ['id', 'name', 'layouts', 'widget_types', 'created_at', 'updated_at']
        read_only_fields = ['user', 'created_at', 'updated_at']

    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
