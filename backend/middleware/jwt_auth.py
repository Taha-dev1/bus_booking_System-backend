from urllib.parse import parse_qs
import jwt
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model

User = get_user_model()

class JWTAuthMiddleware:
    """
    Custom JWT middleware for Django Channels (ASGI)
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # Default to anonymous
        scope["user"] = AnonymousUser()

        # Extract token from query string
        query_string = scope.get("query_string", b"").decode()
        token = parse_qs(query_string).get("token", [None])[0]

        if token:
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
                user_id = payload.get("user_id")
                if user_id:
                    try:
                        user = await User.objects.aget(id=user_id)
                        scope["user"] = user
                    except User.DoesNotExist:
                        pass
            except jwt.ExpiredSignatureError:
                pass
            except jwt.InvalidTokenError:
                pass

        return await self.app(scope, receive, send)


# Wrap middleware in a function for Channels
def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
