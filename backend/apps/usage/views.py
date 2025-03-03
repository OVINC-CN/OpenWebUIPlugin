from apps.usage.authentication import BearerTokenAuthentication
from apps.usage.models import AIModel, UsageLog, UserBalance
from apps.usage.serializers import UsageInletSerializer, UsageOutletSerializer
from ovinc_client.core.auth import LoginRequiredAuthenticate
from ovinc_client.core.viewsets import MainViewSet
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response


class UsageViewSet(MainViewSet):
    """
    Usage API
    """

    queryset = UsageLog.objects.all()
    authentication_classes = [BearerTokenAuthentication, LoginRequiredAuthenticate]

    @action(methods=["POST"], detail=False)
    def inlet(self, request: Request, *args, **kwargs) -> Response:
        req_slz = UsageInletSerializer(data=request.data)
        req_slz.is_valid(raise_exception=True)
        req_data = req_slz.validated_data
        balance = UserBalance.get_balance(
            user_id=req_data["user"]["id"], user_name=req_data["user"]["name"], email=req_data["user"]["email"]
        )
        return Response({"balance": float(balance.balance)})

    @action(methods=["POST"], detail=False)
    def outlet(self, request: Request, *args, **kwargs) -> Response:
        req_slz = UsageOutletSerializer(data=request.data)
        req_slz.is_valid(raise_exception=True)
        req_data = req_slz.validated_data
        usage = req_data["body"]["messages"][-1]["usage"]
        log = UsageLog.record(
            user_id=req_data["user"]["id"],
            chat_id=req_data["body"]["chat_id"],
            model=AIModel.get_model(req_data["body"]["model"]),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            usage=usage,
        )
        balance = UserBalance.get_balance(
            user_id=req_data["user"]["id"], user_name=req_data["user"]["name"], email=req_data["user"]["email"]
        )
        return Response(
            {
                "prompt_tokens": log.prompt_tokens,
                "completion_tokens": log.completion_tokens,
                "cost": float(
                    log.prompt_tokens * log.prompt_price / 1000 / 1000
                    + log.completion_tokens * log.completion_price / 1000 / 1000
                ),
                "balance": float(balance.balance),
            }
        )
