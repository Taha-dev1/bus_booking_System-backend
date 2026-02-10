# quotations/routing.py
from django.urls import path,re_path
from .consumers import ChatConsumer, NotificationConsumer

# This variable name must match what asgi.py imports
websocket_urlpatterns = [
    path("ws/leads/<int:lead_id>/chat/", ChatConsumer.as_asgi()),
    re_path(r"ws/notifications/$", NotificationConsumer.as_asgi()),
]