from django.apps import AppConfig
from django.utils.translation import gettext_lazy


class UsageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.usage"
    verbose_name = gettext_lazy("Usage Module")
