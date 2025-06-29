# File: ta/serializers.py
# ────────────────────────────────
from rest_framework import serializers
from .models import TAAnalysis


class TAAnalysisSerializer(serializers.ModelSerializer):
    class Meta:
        model = TAAnalysis
        fields = "__all__"
        read_only_fields = ("id", "created_at")
