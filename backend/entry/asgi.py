import os

from channels.routing import ProtocolTypeRouter
from django.core.asgi import get_asgi_application
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "entry.settings")

application = ProtocolTypeRouter(
    {
        "http": OpenTelemetryMiddleware(get_asgi_application()),
    }
)
