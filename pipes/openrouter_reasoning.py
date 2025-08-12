"""
title: OpenRouter Reasoning
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.1
licence: MIT
"""

import copy
import json
import logging

from httpx import AsyncClient
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel("INFO")


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://openrouter.ai/api/v1", description="openrouter base url")
        api_key: str = Field(default="", description="openrouter api key")
        request_timeout: int = Field(default=60, description="request timeout")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        models = ["anthropic/claude-3.7-sonnet"]
        return [{"id": model, "name": model} for model in models]

    async def pipe(self, body: dict, __event_emitter__: callable):
        modified_body = copy.deepcopy(body)
        if "model" in modified_body:
            modified_body["model"] = modified_body["model"].split(".", 1)[-1]
        modified_body["reasoning"] = {"exclude": False}

        headers = {
            "Authorization": f"Bearer {self.valves.api_key}",
            "Content-Type": "application/json",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0"
            ),
        }
        params = {
            "method": "POST",
            "url": f"{self.valves.base_url}/chat/completions",
            "json": modified_body,
            "headers": headers,
        }
        try:
            if body.get("stream", False):
                params["json"]["stream_options"] = {"include_usages": True}
                return self._handle_streaming_request(params, __event_emitter__)
            return await self._handle_normal_request(params)
        except Exception as err:
            logger.exception("reasoning error: %s", err)
            raise err

    async def _handle_normal_request(self, params: dict):
        async with AsyncClient(http2=True, timeout=self.valves.request_timeout) as client:
            response = await client.request(**params)
            response.raise_for_status()
            data = response.json()
            if "choices" in data:
                for choice in data["choices"]:
                    if "message" in choice and "reasoning" in choice["message"]:
                        reasoning = choice["message"]["reasoning"]
                        choice["message"]["content"] = f"<think>{reasoning}</think>\n{choice['message']['content']}"
            return data

    async def _handle_streaming_request(self, params: dict, event_emitter: callable):
        async with AsyncClient(http2=True, timeout=self.valves.request_timeout) as client:
            async with client.stream(**params) as response:
                response.raise_for_status()
                thinking_state = -1  # -1: not started, 0: thinking, 1: answered
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    if line.startswith("data: [DONE]"):
                        yield {"done": True}
                        return
                    data = json.loads(line.lstrip("data: "))
                    usage = data.get("usage")
                    if usage:
                        yield {"usage": usage}
                    choices = data.get("choices")
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    reasoning = delta.get("reasoning")
                    content = delta.get("content")
                    if thinking_state == -1 and reasoning:
                        thinking_state = 0
                        yield "<think>"
                    if thinking_state == 0 and not reasoning and content:
                        thinking_state = 1
                        yield "</think>\n\n"
                    content = reasoning or content
                    if content:
                        yield content
