from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChartProfileViewSet

router = DefaultRouter()
router.register(r'profiles', ChartProfileViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('profiles/default/', ChartProfileViewSet.as_view({'get': 'default'}), name='chartprofile-default'),
]
