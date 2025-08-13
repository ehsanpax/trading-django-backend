import redis
import json
from django.conf import settings
from datetime import datetime

class MonitoringService:
    def __init__(self):
        self.redis_client = redis.Redis(host=settings.CHANNEL_LAYERS['default']['CONFIG']['hosts'][0][0],
                                        port=settings.CHANNEL_LAYERS['default']['CONFIG']['hosts'][0][1],
                                        db=0, decode_responses=True)
        self.prefix = "ws_connection:"

    def register_connection(self, channel_name, user, account_id, connection_type, connection_details):
        key = f"{self.prefix}{channel_name}"
        data = {
            "user_id": user.id if user else None,
            "account_id": account_id,
            "connection_type": connection_type,
            "connection_details": connection_details,
            "connected_at": datetime.utcnow().isoformat(),
            "last_client_message_at": None,
            "last_server_message_at": None,
            "last_client_message": None,
            "last_server_message": None,
        }
        self.redis_client.set(key, json.dumps(data))

    def unregister_connection(self, channel_name):
        key = f"{self.prefix}{channel_name}"
        self.redis_client.delete(key)

    def _update_connection_data(self, channel_name, updates):
        key = f"{self.prefix}{channel_name}"
        try:
            data_str = self.redis_client.get(key)
            if data_str:
                data = json.loads(data_str)
                data.update(updates)
                self.redis_client.set(key, json.dumps(data))
        except (redis.RedisError, json.JSONDecodeError) as e:
            print(f"Error updating connection data for {channel_name}: {e}") # Replace with proper logging

    def update_client_message(self, channel_name, message):
        updates = {
            "last_client_message": message,
            "last_client_message_at": datetime.utcnow().isoformat()
        }
        self._update_connection_data(channel_name, updates)

    def update_server_message(self, channel_name, message):
        updates = {
            "last_server_message": message,
            "last_server_message_at": datetime.utcnow().isoformat()
        }
        self._update_connection_data(channel_name, updates)

    def get_all_connections(self):
        keys = self.redis_client.keys(f"{self.prefix}*")
        connections = []
        for key in keys:
            data = self.redis_client.get(key)
            if data:
                connections.append(json.loads(data))
        return connections

monitoring_service = MonitoringService()
