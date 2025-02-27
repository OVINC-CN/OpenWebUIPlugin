"""
title: Usage Monitor
author: VariantConst & OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.3.4
requirements: httpx
license: MIT
"""

import logging
from typing import Dict, Optional

from httpx import AsyncClient
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CustomException(Exception):
    pass


class Filter:
    class Valves(BaseModel):
        api_endpoint: str = Field(default="", description="openwebui-monitor's base url")
        api_key: str = Field(default="", description="openwebui-monitor's api key")
        priority: int = Field(default=5, description="filter priority")

    def __init__(self):
        self.type = "filter"
        self.valves = self.Valves()
        self.outage_map: Dict[str, bool] = {}

    async def request(self, client: AsyncClient, url: str, headers: dict, json: dict):
        response = await client.post(url=url, headers=headers, json=json)
        response.raise_for_status()
        response_data = response.json()
        if not response_data.get("success"):
            logger.error("[usage_monitor] req monitor failed: %s", response_data)
            raise CustomException("calculate usage failed, please contact administrator")
        return response_data

    async def inlet(self, body: dict, __metadata__: Optional[dict] = None, __user__: Optional[dict] = None) -> dict:
        __user__ = __user__ or {}
        __metadata__ = __metadata__ or {}
        user_id = __user__["id"]

        client = AsyncClient()

        try:
            response_data = await self.request(
                client=client,
                url=f"{self.valves.api_endpoint}/api/v1/inlet",
                headers={"Authorization": f"Bearer {self.valves.api_key}"},
                json={"user": __user__, "body": body},
            )
            self.outage_map[user_id] = response_data.get("balance", 0) <= 0
            if self.outage_map[user_id]:
                logger.info("[usage_monitor] no balance: %s", user_id)
                raise CustomException("no balance, please contact administrator")

            return body

        except Exception as err:
            logger.exception("[usage_monitor] error calculating usage: %s", err)
            if isinstance(err, CustomException):
                raise err
            raise Exception(f"error calculating usage, {err}") from err

        finally:
            await client.aclose()

    async def outlet(
        self,
        body: dict,
        __metadata__: Optional[dict] = None,
        __user__: Optional[dict] = None,
        __event_emitter__: callable = None,
    ) -> dict:
        __user__ = __user__ or {}
        __metadata__ = __metadata__ or {}
        user_id = __user__["id"]

        if self.outage_map[user_id]:
            return body

        client = AsyncClient()

        try:
            response_data = await self.request(
                client=client,
                url=f"{self.valves.api_endpoint}/api/v1/outlet",
                headers={"Authorization": f"Bearer {self.valves.api_key}"},
                json={"user": __user__, "body": body},
            )

            # pylint: disable=C0209
            stats = " | ".join(
                [
                    f"Tokens: {response_data['inputTokens']} + {response_data['outputTokens']}",
                    "Cost: %.4f" % response_data["totalCost"],
                    "Balance: %.4f" % response_data["newBalance"],
                ]
            )

            await __event_emitter__({"type": "status", "data": {"description": stats, "done": True}})

            logger.info("usage_monitor: %s %s", user_id, stats)
            return body

        except Exception as err:
            logger.exception("[usage_monitor] error calculating usage: %s", err)
            raise Exception(f"error calculating usage, {err}") from err

        finally:
            await client.aclose()
