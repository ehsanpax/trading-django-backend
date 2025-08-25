from django.urls import path
from .views import (
    PromptViewSet,
    StoreSessionExecutionViewset,
    ChatSessionViewset,
    TradeJournalViewset,
    SessionScheduleViewset,
)


urlpatterns = [
    path(
        "prompts/<pk>/",
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
        "session-schedules/<pk>/",
        SessionScheduleViewset.as_view(
            {"get": "retrieve", "put": "partial_update", "delete": "destroy"}
        ),
    ),
    path(
        "session-schedules/",
        SessionScheduleViewset.as_view({"get": "list", "post": "create"}),
        name="session-schedule-list-create",
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
        "chat-sessions/<pk>/archive/",
        ChatSessionViewset.as_view({"post": "archive"}),
        name="chat-session-archive",
    ),
    path(
        "chat-sessions/<pk>/unarchive/",
        ChatSessionViewset.as_view({"post": "unarchive"}),
        name="chat-session-unarchive",
    ),
    path(
        "trade-journals/",
        TradeJournalViewset.as_view({"get": "list"}),
        name="trade-journal-list",
    ),
]
