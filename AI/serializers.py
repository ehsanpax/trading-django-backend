from rest_framework import serializers
from .models import Prompt, Execution, ChatSession, SessionExecution


class PromptSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prompt
        fields = ["id", "name", "prompt", "version", "user", "is_globally_shared"]
        read_only_fields = [
            "user"
        ]  # User is set by the view, not directly by the client


class SessionExecutionSerializer(serializers.Serializer):
    external_execution_id = serializers.CharField(
        max_length=255,
        required=False,
    )
    external_session_id = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    metadata = serializers.JSONField(default=dict, required=False)
    user_first_message = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )
    session_data = serializers.JSONField(default=dict, required=False)
    total_cost = serializers.FloatField(required=False, allow_null=True)

    def save(self, **kwargs):
        user = self.context["request"].user
        chat_session = ChatSession.objects.filter(
            external_session_id=self.validated_data.get("external_session_id")
        ).first()
        if not chat_session:
            chat_session = ChatSession.objects.create(
                external_session_id=self.validated_data.get("external_session_id"),
                user_first_message=self.validated_data.get("user_first_message"),
                session_data=self.validated_data.get("session_data"),
                user=user,
            )
        execution = Execution.objects.create(
            external_execution_id=self.validated_data.get("external_execution_id"),
            user=user,
            total_cost=self.validated_data.get("total_cost"),
            metadata=self.validated_data.get("metadata"),
        )
        session_execution = SessionExecution.objects.create(
            session=chat_session,
            execution=execution,
        )
        return session_execution


class ChatSessionSerializer(serializers.ModelSerializer):

    class Meta:
        model = ChatSession
        fields = [
            "id",
            "external_session_id",
            "user_first_message",
            "session_data",
            "user",
            "created_at",
        ]
        read_only_fields = [
            "user"
        ]  # User is set by the view, not directly by the client
