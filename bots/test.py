import os
import sys
import django
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trading_platform.settings")
django.setup()

channel_layer = get_channel_layer()
if channel_layer:
    print("Channel layer found. Sending message...")
    async_to_sync(channel_layer.group_send)(
        "test_group",
        {
            "type": "test.message",
            "text": "Hello, Channels!",
        }
    )
    print("Message sent.")
else:
    print("Channel layer not found. Please check your CHANNEL_LAYERS setting.")
