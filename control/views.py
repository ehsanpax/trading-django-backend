from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .services import ControlService

class InstanceControlView(APIView):
    def post(self, request, instance_id, action):
        service = ControlService(instance_id)

        if action == "shutdown":
            result = service.shutdown()
            return Response(result, status=status.HTTP_200_OK)
        else:
            return Response({"status": "error", "message": "Action not supported"}, status=status.HTTP_400_BAD_REQUEST)
