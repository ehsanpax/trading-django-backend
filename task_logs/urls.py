from django.urls import path
from .views import TaskLogListView

urlpatterns = [
    path('task-logs/<str:task_id>/', TaskLogListView.as_view(), name='task-log-list'),
]
