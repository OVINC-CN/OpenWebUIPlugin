"""
title: Rate Limit (Redis)
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Rate Limit
version: 0.0.2
licence: MIT
"""

import datetime
import logging
from typing import Dict, List, Optional, Tuple

import pytz
import redis
from open_webui.env import REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT, REDIS_URL
from open_webui.utils.redis import get_redis_connection, get_sentinels_from_env
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="filter priority")
        requests_per_minute: Optional[int] = Field(default=10, description="每分钟最大请求数")
        requests_per_hour: Optional[int] = Field(default=120, description="每小时最大请求数")
        user_whitelist: Optional[str] = Field(default="", description="用户白名单")
        timezone: str = Field(default="Asia/Shanghai", description="时区")

    def __init__(self):
        self.file_handler = False
        self.valves = self.Valves()
        self.user_map: Dict[str, List[float]] = {}
        self._redis: redis.Redis = get_redis_connection(
            redis_url=REDIS_URL,
            redis_sentinels=get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT),
            decode_responses=True,
        )

    def _key(self, user_id: str, start_from: str) -> str:
        return f"rate_limit:filter:{user_id}:{start_from}"

    def _check_rate(self, user_id: str) -> Tuple[bool, Optional[datetime.datetime], int]:
        # init time
        now = datetime.datetime.now(tz=pytz.timezone(self.valves.timezone))

        # check minute
        minute_now = datetime.datetime(
            year=now.year,
            month=now.month,
            day=now.day,
            hour=now.hour,
            minute=now.minute,
            tzinfo=now.tzinfo,
        )
        minute_start_from = minute_now.strftime("%Y%m%d%H%M")
        minute_key = self._key(user_id, minute_start_from)
        self._redis.expire(name=minute_key, time=datetime.timedelta(minutes=1))
        val = self._redis.incrby(name=minute_key, amount=1)
        self._redis.expire(name=minute_key, time=datetime.timedelta(minutes=1))
        if val > self.valves.requests_per_minute:
            return True, minute_now + datetime.timedelta(minutes=1), val

        # check hour
        hour_now = datetime.datetime(
            year=now.year,
            month=now.month,
            day=now.day,
            hour=now.hour,
            tzinfo=now.tzinfo,
        )
        hour_start_from = hour_now.strftime("%Y%m%d%H")
        hour_key = self._key(user_id, hour_start_from)
        val = self._redis.incrby(name=hour_key, amount=1)
        self._redis.expire(name=hour_key, time=datetime.timedelta(hours=1))
        if val > self.valves.requests_per_hour:
            return True, hour_now + datetime.timedelta(hours=1), val

        return False, None, 0

    def inlet(
        self,
        body: dict,
        __user__: Optional[dict] = None,
    ) -> dict:

        __user__ = __user__ or {}
        user_id = __user__.get("id", "unknown_user")

        if user_id in self.valves.user_whitelist.split(","):
            return body

        rate_limited, future_time, request_count = self._check_rate(user_id)
        if rate_limited:
            future_time_str = future_time.strftime("%H:%M %Z")
            logger.info("[rate_limit] %s %d %s", user_id, request_count, future_time_str)
            raise Exception(f"请求频率过高({request_count})，请等待至{future_time_str}后再试")

        return body
