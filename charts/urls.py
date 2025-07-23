from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChartProfileViewSet

router = DefaultRouter()
router.register(r'profiles', ChartProfileViewSet, basename='chartprofile')

urlpatterns = [
    path('', include(router.urls)),
]
