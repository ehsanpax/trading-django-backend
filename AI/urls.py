from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PromptViewSet

router = DefaultRouter()
router.register(r'prompts', PromptViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
