import os
import django
from django.core.asgi import get_asgi_application

# 1️⃣ Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

# 2️⃣ Setup Django
django.setup()

# 3️⃣ Import Channels routing AFTER setup
from channels.routing import ProtocolTypeRouter, URLRouter
from backend.middleware.jwt_auth import JWTAuthMiddleware
from quotations.routing import websocket_urlpatterns

# 4️⃣ ASGI application
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": JWTAuthMiddleware(
        URLRouter(websocket_urlpatterns)
    ),
})
