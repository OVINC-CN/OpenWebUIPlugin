"""
title: OpenRouter Reasoning
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.1
licence: MIT
"""

import copy
import json
import logging
import time

from httpx import AsyncClient
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel("INFO")


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="", description="openrouter base url")
        api_key: str = Field(default="", description="openrouter api key")
        request_timeout: int = Field(default=60, description="request timeout")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        models = ["o-claude-3.7-sonnet-thinking"]
        return [{"id": f"reasoning/{model}", "name": f"reasoning/{model}"} for model in models]

    async def pipe(self, body: dict, __event_emitter__: callable):
        modified_body = copy.deepcopy(body)
        if "model" in modified_body:
            modified_body["model"] = modified_body["model"].split(".", 1)[-1].replace("reasoning/", "", 1)
        modified_body["include_reasoning"] = True

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
        client = AsyncClient(timeout=self.valves.request_timeout)
        try:
            if body.get("stream", False):
                params["json"]["stream_options"] = {"include_usages": True}
                return self._handle_streaming_request(client, params, __event_emitter__)
            return await self._handle_normal_request(client, params)
        except Exception as err:
            logger.exception("reasoning error: %s", err)
            raise err

    async def _handle_normal_request(self, client: AsyncClient, params: dict):
        response = await client.request(**params)
        response.raise_for_status()
        data = response.json()
        if "choices" in data:
            for choice in data["choices"]:
                if "message" in choice and "reasoning" in choice["message"]:
                    reasoning = choice["message"]["reasoning"]
                    choice["message"]["content"] = f"<think>{reasoning}</think>\n{choice['message']['content']}"
        return data

    async def _handle_streaming_request(self, client: AsyncClient, params: dict, event_emitter: callable):
        async with client.stream(**params) as response:
            response.raise_for_status()
            thinking_state = -1  # -1: not started, 0: thinking, 1: answered
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = json.loads(line.lstrip("data: "))
                choices = data.get("choices")
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                reasoning = delta.get("reasoning")
                content = delta.get("content")
                if thinking_state == -1 and reasoning:
                    thinking_state = 0
                    yield self._construct_chunk("<think>", data)
                if thinking_state == 0 and not reasoning and content:
                    thinking_state = 1
                    yield self._construct_chunk("</think>\n\n", data)
                content = reasoning or content
                if content:
                    yield self._construct_chunk(content, data)
                usage = data.get("usage")
                if usage:
                    yield {"usage": usage}
                    return

    def _construct_chunk(self, content: str, data):
        return {
            "id": data.get("id"),
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "choices": [{"index": 0, "delta": {"content": content, "role": "assistant"}, "finish_reason": None}],
        }
