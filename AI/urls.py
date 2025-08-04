from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PromptViewSet,
    StoreSessionExecutionViewset,
    ChatSessionViewset,
    TradeJournalViewset,
)


urlpatterns = [
    path(
        "prompts/<uuid:pk>/",
        PromptViewSet.as_view(
            {"get": "retrieve", "put": "partial_update", "delete": "destroy"}
        ),
        name="prompt-detail",
    ),
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
    path(
        "trade-journals/",
        TradeJournalViewset.as_view({"get": "list"}),
        name="trade-journal-list",
    ),
]
