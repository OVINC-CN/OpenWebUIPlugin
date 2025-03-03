from django.apps import AppConfig
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy


class HomeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.home"
    verbose_name = gettext_lazy("Home Module")

    def ready(self):
        if not settings.ADMIN_USERNAME or not settings.ADMIN_PASSWORD:
            return

        user_model = get_user_model()
        user, _ = user_model.objects.get_or_create(username=settings.ADMIN_USERNAME)
        user.set_password(settings.ADMIN_PASSWORD)
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=["password", "is_superuser", "is_staff"])
