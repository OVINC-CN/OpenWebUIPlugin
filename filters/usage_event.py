"""
title: Usage Event
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Usage Event
version: 0.0.1
licence: MIT
"""

import logging
import math
import time

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="filter priority")

    def __init__(self):
        self.valves = self.Valves()
        self.start_time = time.time_ns()

    async def inlet(self, body: dict) -> dict:
        self.start_time = time.time_ns()
        return body

    async def outlet(
        self,
        body: dict,
        __event_emitter__: callable = None,
    ) -> dict:

        # check body
        if not body or not isinstance(body, dict):
            return body

        # load messages
        messages = body.get("messages") or []
        if not messages:
            return body

        # load usage
        message = messages[-1]
        usage = message.get("usage")
        if not usage:
            return body

        # record end time
        end_time = time.time_ns()
        duration = math.ceil((end_time - self.start_time) / 1e9)
        if duration >= 60:
            duration_text = "%dm%ds" % (duration // 60, duration % 60)
        else:
            duration_text = "%ds" % duration

        # load data
        prompt_tokens = usage.get("prompt_tokens", 0)
        completions_tokens = usage.get("completion_tokens", 0)
        total_cost = usage.get("total_cost", 0)
        total_cost = "< ¥0.01" if total_cost < 0.01 else "¥%.2f" % total_cost

        # log usage
        description = (
            "Tokens: %(prompt_tokens)d + %(completions_tokens)d | "
            "Cost: %(total_cost)s | "
            "Duration: %(total_time)s | "
            "TPS: %(tps)d"
        ) % {
            "prompt_tokens": prompt_tokens,
            "completions_tokens": completions_tokens,
            "total_cost": total_cost,
            "total_time": duration_text,
            "tps": completions_tokens / duration,
        }
        if __event_emitter__:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {
                        "description": description,
                        "done": True,
                        "hidden": False,
                    },
                }
            )

        return body
