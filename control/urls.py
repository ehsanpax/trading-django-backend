from django.urls import path
from .views import InstanceControlView

urlpatterns = [
    path('instance/<uuid:instance_id>/<str:action>/', InstanceControlView.as_view(), name='instance_control'),
]
