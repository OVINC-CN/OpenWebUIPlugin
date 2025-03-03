from apps.usage.models import AIModel, UsageLog, UserBalance
from apps.usage.utils import ModelSyncer
from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.translation import gettext_lazy


@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = ("model_id", "prompt_price", "completion_price")
    ordering = ("model_name",)
    search_fields = ("model_id",)
    actions = ("sync_models",)
    list_editable = ("prompt_price", "completion_price")

    @admin.action(description=gettext_lazy("Sync Models"))
    def sync_models(self, request: HttpRequest, queryset: QuerySet[AIModel]):
        ModelSyncer().sync()


@admin.register(UserBalance)
class UserBalanceAdmin(admin.ModelAdmin):
    list_display = ("user_id", "user_name", "email", "balance")
    ordering = ("user_name",)
    search_fields = ("user_name",)


@admin.register(UsageLog)
class UsageLogAdmin(admin.ModelAdmin):
    list_display = ("id", "user_id", "user_name", "model", "prompt_tokens", "completion_tokens", "price", "chat_at")
    ordering = ("-chat_at",)
    list_filter = ("model",)
    search_fields = ("user_id",)

    @admin.display(description=gettext_lazy("User Name"))
    def user_name(self, obj: UsageLog) -> str:
        if not obj.user_info:
            return ""
        return obj.user_info.get("name")

    @admin.display(description=gettext_lazy("Price"))
    def price(self, obj: UsageLog) -> str:
        return (
            obj.prompt_price * obj.prompt_tokens / 1000 / 1000
            + obj.completion_price * obj.completion_tokens / 1000 / 1000
        )
