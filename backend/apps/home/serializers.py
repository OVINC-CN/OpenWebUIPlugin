from apps.home.exceptions import LanguageCodeInvalid
from django.utils.translation import check_for_language, gettext_lazy
from rest_framework import serializers


class I18nRequestSerializer(serializers.Serializer):
    """
    I18n
    """

    language = serializers.CharField(label=gettext_lazy("Language Code"))

    def validate_language(self, language: str) -> str:
        if check_for_language(language):
            return language
        raise LanguageCodeInvalid()
