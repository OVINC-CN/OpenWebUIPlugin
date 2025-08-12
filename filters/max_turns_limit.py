"""
title: Max Turns Filter
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Max Turns Filter
version: 0.0.1
licence: MIT
"""

import logging
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="filter priority")
        max_turns: int = Field(default=16, description="maximum conversation turns")

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        __user__ = __user__ or {}
        current_turns = len(body.get("messages", [])) // 2
        if current_turns >= self.valves.max_turns:
            logger.info("[max_turns_reached] %s", __user__.get("id"))
            raise Exception(f"max turns ({self.valves.max_turns}) reached, new conversation required")
        return body
