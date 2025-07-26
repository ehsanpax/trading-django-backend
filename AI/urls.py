from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PromptViewSet, StoreSessionExecutionViewset, ChatSessionViewset


urlpatterns = [
    path(
        "prompts/",
        PromptViewSet.as_view({"get": "list", "post": "create"}),
        name="prompt-list-create",
    ),
    path(
        "session-executions/",
        StoreSessionExecutionViewset.as_view(),
        name="session-execution-create",
    ),
    path(
        "chat-sessions/",
        ChatSessionViewset.as_view({"get": "list"}),
        name="chat-session-list-create",
    ),
]
