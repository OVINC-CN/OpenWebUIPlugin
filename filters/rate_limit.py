"""
title: Rate Limit
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Rate Limit
requirements: pytz
version: 0.0.1
licence: MIT
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from pytz import timezone

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="filter priority")
        requests_per_minute: Optional[int] = Field(default=10, description="maximum requests allowed per minute")
        requests_per_hour: Optional[int] = Field(default=120, description="maximum requests allowed per hour")
        timezone: str = Field(default="Asia/Shanghai", description="timezone")

    def __init__(self):
        self.file_handler = False
        self.valves = self.Valves()
        self.user_map: Dict[str, List[float]] = {}

    def _check_rate(self, user_id: str) -> Tuple[bool, Optional[int], int]:
        # init time
        now = time.time()

        # init user request points
        if user_id not in self.user_map:
            self.user_map[user_id] = []

        # load user requests
        self.user_map[user_id] = [
            point
            for point in self.user_map[user_id]
            if (
                (self.valves.requests_per_minute is not None and now - point < 60)
                or (self.valves.requests_per_hour is not None and now - point < 3600)
            )
        ]
        points = self.user_map[user_id]

        # rpm
        last_minute_reqs = [point for point in points if now - point < 60]
        if len(last_minute_reqs) >= self.valves.requests_per_minute:
            return True, int(60 - (time.time() - min(last_minute_reqs))), len(last_minute_reqs)

        # rph
        last_hour_reqs = [point for point in points if now - point < 3600]
        if len(last_hour_reqs) >= self.valves.requests_per_hour:
            return True, int(3600 - (time.time() - min(last_hour_reqs))), len(last_hour_reqs)

        return False, None, len(points)

    def _log_request(self, user_id: str):
        self.user_map[user_id].append(time.time())

    def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
    ) -> dict:

        __user__ = __user__ or {}
        if not __user__:
            return body

        user_id = __user__.get("id", "unknown_user")

        rate_limited, wait_time, request_count = self._check_rate(user_id)
        if rate_limited:
            future_time = datetime.now().astimezone(timezone(self.valves.timezone)) + timedelta(seconds=wait_time)
            future_time_str = future_time.strftime("%H:%M %Z")
            logger.info("[rate_limit] %s %d %s", user_id, request_count, future_time_str)
            raise Exception(f"too many requests ({request_count}), please wait until {future_time_str}")

        self._log_request(user_id)
        return body
