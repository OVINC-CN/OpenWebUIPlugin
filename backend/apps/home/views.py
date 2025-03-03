from apps.home.serializers import I18nRequestSerializer
from django.conf import settings
from django.conf.global_settings import LANGUAGE_COOKIE_NAME
from django.contrib.auth import get_user_model
from ovinc_client.account.models import User
from ovinc_client.core.auth import SessionAuthenticate
from ovinc_client.core.viewsets import MainViewSet
from rest_framework.response import Response

USER_MODEL: User = get_user_model()


class HomeView(MainViewSet):
    """
    Home View
    """

    queryset = USER_MODEL.get_queryset()
    authentication_classes = [SessionAuthenticate]

    def list(self, request, *args, **kwargs):
        msg = f"[{request.method}] Connect Success"
        return Response({"resp": msg, "user": request.user.username})


# pylint: disable=R0901
class I18nViewSet(MainViewSet):
    """
    International
    """

    authentication_classes = [SessionAuthenticate]

    def create(self, request, *args, **kwargs):
        """
        Change Language
        """

        # Varify Request Data
        request_serializer = I18nRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        request_data = request_serializer.validated_data

        # Change Lang
        lang_code = request_data["language"]
        response = Response()
        response.set_cookie(
            LANGUAGE_COOKIE_NAME,
            lang_code,
            max_age=settings.SESSION_COOKIE_AGE,
            domain=settings.SESSION_COOKIE_DOMAIN,
            path=settings.SESSION_COOKIE_PATH,
            secure=settings.SESSION_COOKIE_SECURE or None,
            httponly=settings.SESSION_COOKIE_HTTPONLY or None,
            samesite=settings.SESSION_COOKIE_SAMESITE,
        )
        return response
