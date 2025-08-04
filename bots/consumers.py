import json
from channels.generic.websocket import AsyncWebsocketConsumer
from monitoring.services import monitoring_service

class BacktestConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.backtest_run_id = self.scope['url_route']['kwargs']['backtest_run_id']
        self.backtest_group_name = f'backtest_{self.backtest_run_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.backtest_group_name,
            self.channel_name
        )

        await self.accept()

        monitoring_service.register_connection(
            self.channel_name,
            self.scope.get("user"),
            self.backtest_run_id,
            "backtest",
            {"backtest_run_id": self.backtest_run_id}
        )

    async def disconnect(self, close_code):
        monitoring_service.unregister_connection(self.channel_name)
        # Leave room group
        await self.channel_layer.group_discard(
            self.backtest_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        monitoring_service.update_client_message(self.channel_name, text_data)
        pass

    # Receive message from room group
    async def backtest_progress(self, event):
        progress = event['progress']
        status = event.get('status', 'RUNNING')

        # Send message to WebSocket
        payload = {
            'progress': progress,
            'status': status
        }
        await self.send(text_data=json.dumps(payload))
        monitoring_service.update_server_message(self.channel_name, payload)
