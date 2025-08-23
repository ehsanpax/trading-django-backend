from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser
from .services import monitoring_service
from trading_platform.mt5_api_client import connection_manager
from datetime import datetime

class ConnectionStatusView(APIView):
    """
    Provides a snapshot of all active websocket connections.
    Requires admin privileges.
    """
    permission_classes = [IsAdminUser]

    def get(self, request, *args, **kwargs):
        connections = monitoring_service.get_all_connections()
        
        for conn in connections:
            conn['health_status'] = self.get_health_status(conn)
            
        return Response(connections)

    def get_health_status(self, conn):
        # Client to Backend Health
        last_message_time_str = conn.get('last_client_message_at')
        client_to_backend = "HEALTHY"
        if last_message_time_str:
            last_message_time = datetime.fromisoformat(last_message_time_str)
            if (datetime.utcnow() - last_message_time).total_seconds() > 60:
                client_to_backend = "UNHEALTHY"
        
        # Backend to MT5 Health
        backend_to_mt5 = "NOT_APPLICABLE"
        if conn.get('connection_type') in ['price', 'account']:
            internal_account_id = conn.get('account_id')
            if internal_account_id in connection_manager._connections:
                mt5_client = connection_manager._connections[internal_account_id]
                backend_to_mt5 = "HEALTHY" if mt5_client.is_connected else "UNHEALTHY"
            else:
                backend_to_mt5 = "UNKNOWN"

        return {
            "client_to_backend": client_to_backend,
            "backend_to_mt5": backend_to_mt5
        }
