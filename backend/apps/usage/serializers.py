from django.utils.translation import gettext_lazy
from rest_framework import serializers


class UserInfoSerializer(serializers.Serializer):
    id = serializers.CharField(label=gettext_lazy("User ID"))
    name = serializers.CharField(label=gettext_lazy("User Name"), allow_blank=True, allow_null=True)
    email = serializers.CharField(label=gettext_lazy("User Email"), allow_blank=True, allow_null=True)
    role = serializers.CharField(label=gettext_lazy("User Role"), allow_blank=True, allow_null=True)


class UsageInletSerializer(serializers.Serializer):
    user = UserInfoSerializer(label=gettext_lazy("User Info"))


class MessageSerializer(serializers.Serializer):
    usage = serializers.JSONField(label=gettext_lazy("Usage Info"), required=False)


class OutletBodySerializer(serializers.Serializer):
    chat_id = serializers.CharField(label=gettext_lazy("Chat ID"))
    model = serializers.CharField(label=gettext_lazy("Model"))
    messages = serializers.ListField(
        label=gettext_lazy("Messages"), child=MessageSerializer(label=gettext_lazy("Message"))
    )

    def validate(self, attrs: dict) -> dict:
        data = super().validate(attrs)
        if "usage" not in data["messages"][-1]:
            raise serializers.ValidationError(gettext_lazy("usage info is required"))
        return data


class UsageOutletSerializer(serializers.Serializer):
    user = UserInfoSerializer(label=gettext_lazy("User Info"))
    body = OutletBodySerializer(label=gettext_lazy("Outlet Body"))
