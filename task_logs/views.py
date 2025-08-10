from rest_framework import generics
from .models import TaskLog
from .serializers import TaskLogSerializer

class TaskLogListView(generics.ListAPIView):
    serializer_class = TaskLogSerializer

    def get_queryset(self):
        task_id = self.kwargs.get('task_id')
        return TaskLog.objects.filter(task_id=task_id)
