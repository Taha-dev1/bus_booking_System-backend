import sys
from django.apps import AppConfig


class QuotationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quotations'

    def ready(self):
        import quotations.signals
        # Don't start scheduler during management commands like migrate
        if 'runserver' in sys.argv or 'gunicorn' in sys.argv:
            try:
                from .scheduler import start_scheduler
                start_scheduler()
            except Exception as e:
                print(f"Scheduler failed to start: {e}")
