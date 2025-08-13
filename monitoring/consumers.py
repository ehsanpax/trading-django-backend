import asyncio
import json
from datetime import datetime
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from .services import monitoring_service
from trading_platform.mt5_api_client import connection_manager

class MonitoringConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        # For simplicity, this consumer is public. In a real-world scenario,
        # you would add authentication here to ensure only authorized users can connect.
        await self.accept()
        self.monitoring_task = asyncio.create_task(self.stream_connection_status())

    async def disconnect(self, close_code):
        if hasattr(self, 'monitoring_task'):
            self.monitoring_task.cancel()

    async def stream_connection_status(self):
        while True:
            connections = monitoring_service.get_all_connections()
            
            # Add health status
            for conn in connections:
                conn['health_status'] = self.get_health_status(conn)

            await self.send_json({
                "type": "connection_update",
                "connections": connections
            })
            await asyncio.sleep(2) # Update interval

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
