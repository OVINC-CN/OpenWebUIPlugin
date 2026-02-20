"""
title: Claude Web Fetch
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
description: Claude Web Fetch
version: 0.0.2
licence: MIT
"""

from typing import Dict

from pydantic import BaseModel, Field


class Filter:
    class Valves(BaseModel):
        max_uses: int = Field(default=0, title="最大使用次数", description="单次请求最大使用次数，0表示无限制")
        allowed_domains: str = Field(
            default="", title="允许的域名", description="允许使用的域名，多个域名用逗号分隔，留空表示不限制"
        )
        blocked_domains: str = Field(
            default="", title="禁止的域名", description="禁止使用的域名，多个域名用逗号分隔，留空表示不限制"
        )
        max_tokens: int = Field(default=0, title="抓取最大Token数", description="0表示不限制")
        priority: int = Field(default=0, description="filter priority")

    def __init__(self):
        self.valves = self.Valves()
        self.toggle = True
        self.icon = (
            "data:image/svg+xml;base64,PHN2ZyBkYXRhLXYtMmJjNjQ2MGU9IiIgdmlld0JveD0iMCAwIDQ4IDQ4IiBmaWxsPSJub25lIiB4bWx"
            "ucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHN0cm9rZT0iY3VycmVudENvbG9yIiBjbGFzcz0iYXJjby1pY29uIGFyY28taWNv"
            "bi1saW5rIiBzdHJva2Utd2lkdGg9IjQiIHN0cm9rZS1saW5lY2FwPSJidXR0IiBzdHJva2UtbGluZWpvaW49Im1pdGVyIiBmaWx0ZXI9I"
            "iIgc3R5bGU9ImZvbnQtc2l6ZTogMzJweDsiPjxwYXRoIGQ9Im0xNC4xIDI1LjQxNC00Ljk1IDQuOTVhNiA2IDAgMCAwIDguNDg2IDguND"
            "g1bDguNDg1LTguNDg1YTYgNiAwIDAgMCAwLTguNDg1bTcuNzc5LjcwNyA0Ljk1LTQuOTVhNiA2IDAgMSAwLTguNDg2LTguNDg1bC04LjQ"
            "4NSA4LjQ4NWE2IDYgMCAwIDAgMCA4LjQ4NSI+PC9wYXRoPjwvc3ZnPg=="
        )

    def inlet(self, body: dict) -> dict:
        tool: Dict[str, any] = {"type": "web_fetch_20260209", "name": "web_fetch"}
        if self.valves.max_uses > 0:
            tool["max_uses"] = self.valves.max_uses
        if self.valves.allowed_domains:
            tool["allowed_domains"] = self.valves.allowed_domains.split(",")
        if self.valves.blocked_domains:
            tool["blocked_domains"] = self.valves.blocked_domains.split(",")
        if self.valves.max_tokens > 0:
            tool["max_content_tokens"] = self.valves.max_tokens
        if body.get("tools"):
            body["tools"].append(tool)
        else:
            body["tools"] = [tool]
        return body
