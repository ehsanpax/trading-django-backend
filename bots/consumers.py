import json
from channels.generic.websocket import AsyncWebsocketConsumer

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

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.backtest_group_name,
            self.channel_name
        )

    # Receive message from WebSocket
    async def receive(self, text_data):
        pass

    # Receive message from room group
    async def backtest_progress(self, event):
        progress = event['progress']
        status = event.get('status', 'RUNNING')

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'progress': progress,
            'status': status
        }))
