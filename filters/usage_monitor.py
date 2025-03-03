"""
title: Usage Monitor
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.3.4
requirements: httpx
license: MIT
"""

import logging

from httpx import AsyncClient, HTTPStatusError
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CustomException(Exception):
    pass


class Filter:
    class Valves(BaseModel):
        api_endpoint: str = Field(default="", description="plugin base url")
        api_key: str = Field(default="", description="plugin api key")
        priority: int = Field(default=5, description="filter priority")

    def __init__(self):
        self.type = "filter"
        self.valves = self.Valves()

    async def request(self, client: AsyncClient, url: str, json: dict):
        response = await client.post(url=url, headers={"Authorization": f"Bearer {self.valves.api_key}"}, json=json)
        try:
            response.raise_for_status()
        except HTTPStatusError as err:
            logger.error("response status invalid: %s %s", response.status_code, response.text)
            raise err
        return response.json()["data"]

    async def inlet(self, body: dict, __user__: dict = None) -> dict:
        user_id = __user__["id"]

        client = AsyncClient()

        try:
            response_data = await self.request(
                client=client,
                url=f"{self.valves.api_endpoint}/usages/inlet/",
                json={"user": __user__},
            )
            if response_data["balance"] <= 0:
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
        __user__: dict,
        __event_emitter__: callable,
    ) -> dict:
        user_id = __user__["id"]

        client = AsyncClient()

        try:
            response_data = await self.request(
                client=client,
                url=f"{self.valves.api_endpoint}/usages/outlet/",
                json={"user": __user__, "body": body},
            )

            # pylint: disable=C0209
            stats = " | ".join(
                [
                    f"Tokens: {response_data['prompt_tokens']} + {response_data['completion_tokens']}",
                    "Cost: %.4f" % response_data["cost"],
                    "Balance: %.4f" % response_data["balance"],
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
