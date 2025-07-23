from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PromptViewSet, StoreSessionExecutionViewset


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
]
