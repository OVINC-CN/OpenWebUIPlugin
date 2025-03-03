from apps.usage.constants import DECIMAL_PLACES, DIGIT_PLACES
from django.conf import settings
from django.db import models, transaction
from django.db.models import F
from django.utils.translation import gettext_lazy
from ovinc_client.core.constants import MAX_CHAR_LENGTH
from ovinc_client.core.logger import logger
from ovinc_client.core.models import BaseModel, ForeignKey, UniqIDField


class PriceBaseModel(BaseModel):
    """
    Price base model
    """

    prompt_price = models.DecimalField(
        verbose_name=gettext_lazy("Prompt Price"),
        help_text=gettext_lazy("Prompt price for 1m tokens"),
        max_digits=DIGIT_PLACES,
        decimal_places=DECIMAL_PLACES,
        default=settings.DEFAULT_TOKEN_PRICE,
    )
    completion_price = models.DecimalField(
        verbose_name=gettext_lazy("Completion Price"),
        help_text=gettext_lazy("Completion price for 1m tokens"),
        max_digits=DIGIT_PLACES,
        decimal_places=DECIMAL_PLACES,
        default=settings.DEFAULT_TOKEN_PRICE,
    )

    class Meta:
        abstract = True


class AIModel(PriceBaseModel):
    """
    AI Model
    """

    model_id = models.CharField(
        verbose_name=gettext_lazy("Model ID"), primary_key=True, max_length=MAX_CHAR_LENGTH, unique=True
    )
    model_name = models.CharField(
        verbose_name=gettext_lazy("Model Name"), max_length=MAX_CHAR_LENGTH, db_index=True, null=True, blank=True
    )

    class Meta:
        verbose_name = gettext_lazy("AI Model")
        verbose_name_plural = verbose_name
        ordering = ["model_name"]

    def __str__(self) -> str:
        return f"{self.model_id}"

    @classmethod
    def get_model(cls, model_id: str) -> "AIModel":
        return cls.objects.get_or_create(model_id=model_id)[0]


class UsageLog(PriceBaseModel):
    """
    Usage Log
    """

    id = UniqIDField(verbose_name=gettext_lazy("ID"), primary_key=True)
    user = ForeignKey(verbose_name=gettext_lazy("User"), to="UserBalance", on_delete=models.PROTECT, null=True)
    chat_id = models.CharField(verbose_name=gettext_lazy("Chat ID"), max_length=MAX_CHAR_LENGTH, db_index=True)
    model = ForeignKey(verbose_name=gettext_lazy("Model"), to="AIModel", on_delete=models.PROTECT)
    prompt_tokens = models.BigIntegerField(verbose_name=gettext_lazy("Prompt Tokens"))
    completion_tokens = models.BigIntegerField(verbose_name=gettext_lazy("Completion Tokens"))
    usage = models.JSONField(verbose_name=gettext_lazy("Usage"), null=True, blank=True, default=dict)
    chat_at = models.DateTimeField(verbose_name=gettext_lazy("Chat at"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = gettext_lazy("Usage Log")
        verbose_name_plural = verbose_name
        ordering = ["-chat_at"]

    def __str__(self) -> str:
        return f"{self.id}:{self.user}"

    # pylint: disable=R0913,R0917
    @classmethod
    @transaction.atomic
    def record(
        cls,
        user_id: str,
        chat_id: str,
        model: AIModel,
        prompt_tokens: int,
        completion_tokens: int,
        usage: dict,
        user_info: dict,
    ) -> "UsageLog":
        log = cls.objects.create(
            user_id=user_id,
            chat_id=chat_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_price=model.prompt_price,
            completion_price=model.completion_price,
            usage=usage,
        )
        # pylint: disable=E1101
        prompt_price = prompt_tokens * model.prompt_price / 1000 / 1000
        completion_price = completion_tokens * model.completion_price / 1000 / 1000
        total_price = prompt_price + completion_price
        UserBalance.objects.filter(user_id=user_id).update(balance=F("balance") - total_price)
        logger.info(
            "[usage log] user: %s, tokens: %d/%s, cost: %.4f", user_info, prompt_tokens, completion_tokens, total_price
        )
        return log


class UserBalance(models.Model):
    """
    User Balance
    """

    user_id = models.CharField(verbose_name=gettext_lazy("User ID"), max_length=MAX_CHAR_LENGTH, primary_key=True)
    user_name = models.CharField(
        verbose_name=gettext_lazy("User Name"), max_length=MAX_CHAR_LENGTH, blank=True, null=True, db_index=True
    )
    email = models.CharField(verbose_name=gettext_lazy("Email"), max_length=MAX_CHAR_LENGTH, blank=True, null=True)
    balance = models.DecimalField(
        verbose_name=gettext_lazy("Balance"), max_digits=DIGIT_PLACES, decimal_places=DECIMAL_PLACES, default=0
    )

    class Meta:
        verbose_name = gettext_lazy("User Balance")
        verbose_name_plural = verbose_name
        ordering = ["user_name"]

    def __str__(self) -> str:
        return f"{self.user_name}:{self.user_id}"

    @classmethod
    def get_balance(cls, user_id: str, user_name: str = "", email: str = "") -> "UserBalance":
        # pylint: disable=E1101
        balance = cls.objects.get_or_create(user_id=user_id, defaults={"user_name": user_name, "email": email})[0]
        if balance.email != email or balance.user_name != user_name:
            balance.email = email
            balance.user_name = user_name
            balance.save(update_fields=["email", "user_name"])
        return balance
