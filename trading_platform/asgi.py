# trading_platform/asgi.py
import os
import django
from django.core.asgi import get_asgi_application

# Set the DJANGO_SETTINGS_MODULE environment variable.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'trading_platform.settings')

# Initialize Django application.
django.setup()

# Import the routing configuration after Django is set up.
from trading_platform.routing import application
