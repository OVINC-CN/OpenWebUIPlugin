"""
title: Current Datetime
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Get current datetime
requirements: pytz
version: 0.0.1
licence: MIT
"""

import logging
from datetime import datetime

from pydantic import BaseModel, Field
from pytz import timezone

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Tools:
    class UserValves(BaseModel):
        timezone: str = Field(default="Asia/Shanghai", description="timezone")
        time_format: str = Field(default="%Y-%m-%dT%H:%M:%S%z", description="time format")

    def __init__(self):
        self.user_valves = self.UserValves()

    async def get_current_datetime(self, __user__: dict, __event_emitter__: callable, __metadata__: dict) -> str:
        """
        Get the current datetime.
        :return: The current datetime as a string.
        """
        logger.info("[get_current_datetime] %s %s", __user__.get("id"), __metadata__.get("chat_id"))
        self.user_valves = __user__.get("valves", self.user_valves)
        current_date = (
            datetime.now().astimezone(timezone(self.user_valves.timezone)).strftime(self.user_valves.time_format)
        )
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": current_date, "done": True, "hidden": False},
            }
        )
        return f"It's {current_date} now"
