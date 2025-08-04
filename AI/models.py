from django.db import models
from django.contrib.auth.models import User
from uuid import uuid4


class Prompt(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    user_prompt = models.TextField()
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    config = models.JSONField(default=dict)
    version = models.IntegerField(default=1)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_prompts")
    is_globally_shared = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} (v{self.version})"

    class Meta:
        unique_together = ("name", "version", "user")

    def save(self, *args, **kwargs):
        last_version_number = 0
        last_version = (
            Prompt.objects.filter(name=self.name, user=self.user)
            .exclude(pk=self.pk)
            .order_by("-version")
            .first()
        )
        if last_version and last_version.version:
            last_version_number = last_version.version
        self.version = last_version_number + 1

        super().save(*args, **kwargs)


class Execution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_executions"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    external_execution_id = models.CharField(max_length=255, blank=True, db_index=True)
    total_cost = models.FloatField(null=True, blank=True)
    result = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("external_execution_id", "user")


class ChatSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ai_chat_sessions"
    )
    external_session_id = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    session_data = models.JSONField(default=dict, blank=True)
    user_first_message = models.TextField(blank=True)

    class Meta:
        unique_together = ("external_session_id", "user")


class SessionExecution(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    session = models.ForeignKey(
        ChatSession, on_delete=models.CASCADE, related_name="executions"
    )
    execution = models.ForeignKey(
        Execution, on_delete=models.CASCADE, related_name="session_executions"
    )

    class Meta:
        unique_together = ("session", "execution")
