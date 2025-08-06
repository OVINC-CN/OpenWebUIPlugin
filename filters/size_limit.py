"""
title: Size Limit
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Check request size limit
version: 0.0.1
licence: MIT
"""

import json
import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="filter priority")
        max_size: int = Field(default=10, description="max request size in mb", ge=0)

    def __init__(self):
        self.valves = self.Valves()

    def inlet(self, body: dict, __user__: dict) -> dict:
        data = json.dumps(body) if isinstance(body, dict) else str(body)
        data_size = len(data.encode("utf-8")) / 1024 / 1024
        if data_size > self.valves.max_size:
            logger.warning(
                "[RequestSizeFilter] %s in %s with %.2fMB exceeds limit of %dMB",
                __user__["name"],
                body["metadata"]["chat_id"],
                data_size,
                self.valves.max_size,
            )
            raise Exception(
                "对话内容大小超出限制，请减少对话内容，当前大小: %.2fMB, 限制大小: %dMB"
                % (data_size, self.valves.max_size)
            )
        return body
