"""
title: DeepSeek Reasoning
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.1
licence: MIT
"""

import json
import logging

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://api.deepseek.com/v1", description="base url")
        api_key: str = Field(default="", description="api key")
        api_model: str = Field(default="deepseek-reasoner", description="model name")
        timeout: int = Field(default=300, description="timeout for requests")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": self.valves.api_model, "name": self.valves.api_model}]

    async def pipe(self, body: dict, __event_emitter__: callable):
        thinking_state = -1
        try:
            model_id = body["model"].split(".", 1)[-1]
            async with httpx.AsyncClient(http2=True) as client:
                async with client.stream(
                    "POST",
                    f"{self.valves.base_url}/chat/completions",
                    json={**body, "model": model_id},
                    headers={
                        "Authorization": f"Bearer {self.valves.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=self.valves.timeout,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        line = line.lstrip("data: ")
                        if line.strip() == "[DONE]":
                            yield {"done": True}
                            return
                        data = json.loads(line)
                        usage = data.get("usage")
                        if usage:
                            yield {"usage": usage}
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        state_output, thinking_state = self._update_thinking_state(delta, thinking_state)
                        if state_output:
                            yield state_output
                        content = delta.get("reasoning_content", "") or delta.get("content", "")
                        if not content:
                            continue
                        if content.startswith("<think>"):
                            content = content.lstrip("<think>")
                            yield "<think>\n"
                        elif content.startswith("</think>"):
                            content = content.lstrip("</think>")
                            yield "</think>\n\n"
                        yield content
        except Exception as err:
            logger.exception("deepseek_reasoning failed: %s", err)
            raise err

    def _update_thinking_state(self, delta: dict, thinking_state: int) -> (str, int):
        state_output = ""
        if thinking_state == -1 and delta.get("reasoning_content"):
            thinking_state = 0
            state_output = "<think>\n"
        elif thinking_state == 0 and not delta.get("reasoning_content") and delta.get("content"):
            thinking_state = 1
            state_output = "\n</think>\n\n"
        return state_output, thinking_state
