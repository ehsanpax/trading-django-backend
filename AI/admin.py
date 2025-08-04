from django.contrib import admin
from .models import Execution, ChatSession, SessionExecution, Prompt


@admin.register(Prompt)
class PromptAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "created_at", "name")
    search_fields = ("id", "name", "user__username")
    list_filter = ("created_at", "user")


@admin.register(Execution)
class ExecutionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "created_at",
        "external_execution_id",
        "total_cost",
    )
    search_fields = ("id", "external_execution_id", "user__username")
    list_filter = ("created_at", "user")


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "external_session_id", "created_at")
    search_fields = ("id", "external_session_id", "user__username")
    list_filter = ("created_at", "user")


@admin.register(SessionExecution)
class SessionExecutionAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "execution")
    search_fields = ("id", "session__id", "execution__id")
    list_filter = ("session", "execution")
