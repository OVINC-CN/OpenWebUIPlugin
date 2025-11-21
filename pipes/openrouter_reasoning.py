"""
title: OpenRouter Reasoning
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.3
licence: MIT
"""

import json
import logging
import time
import uuid
from typing import AsyncIterable, Literal, Optional, Tuple

import httpx
from fastapi import Request
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MAIN"])


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://openrouter.ai/api/v1", title="Base URL")
        api_key: str = Field(default="", title="API Key")
        enable_reasoning: bool = Field(default=True, title="展示思考内容")
        allow_params: str = Field(
            default="", title="透传参数", description="允许配置的参数，使用英文逗号分隔，例如 temperature"
        )
        timeout: int = Field(default=600, title="请求超时时间（秒）")
        proxy: Optional[str] = Field(default="", title="代理地址")
        models: str = Field(default="anthropic/claude-sonnet-4.5", title="模型", description="使用英文逗号分隔多个模型")

    class UserValves(BaseModel):
        reasoning_effort: Literal["low", "medium", "high"] = Field(default="low", title="推理强度")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": model, "name": model} for model in self.valves.models.split(",") if model]

    async def pipe(self, body: dict, __user__: dict, __request__: Request) -> StreamingResponse:
        return StreamingResponse(self._pipe(body=body, __user__=__user__, __request__=__request__))

    async def _pipe(self, body: dict, __user__: dict, __request__: Request) -> AsyncIterable:
        model, payload = await self._build_payload(body=body, user_valves=__user__["valves"])
        try:
            # call client
            async with httpx.AsyncClient(
                base_url=self.valves.base_url,
                headers={"Authorization": f"Bearer {self.valves.api_key}"},
                proxy=self.valves.proxy or None,
                trust_env=True,
                timeout=self.valves.timeout,
            ) as client:
                async with client.stream(**payload) as response:
                    if response.status_code != 200:
                        text = ""
                        async for line in response.aiter_lines():
                            text += line
                        logger.error("response invalid with %d: %s", response.status_code, text)
                        response.raise_for_status()
                        return
                    is_thinking = self.valves.enable_reasoning
                    if is_thinking:
                        yield self._format_data(model=model, content="<think>")
                    async for line in response.aiter_lines():
                        # parse data
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("event:") or not line.startswith("data:"):
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        if line.strip() == "[DONE]":
                            yield self._format_data(model=model, if_finished=True)
                            break
                        if not line.startswith("{"):
                            continue
                        if isinstance(line, str):
                            line = json.loads(line)
                        # choices
                        choices = line.get("choices") or []
                        if not choices:
                            continue
                        # delta
                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        if not delta:
                            continue
                        # reasoning content
                        reasoning_content = delta.get("reasoning") or ""
                        if reasoning_content:
                            yield self._format_data(model=model, content=reasoning_content)
                        # content
                        content = delta.get("content") or ""
                        if content:
                            if is_thinking:
                                is_thinking = False
                                yield self._format_data(model=model, content="</think>")
                            yield self._format_data(model=model, content=content)
                        # usage
                        usage = line.get("usage") or {}
                        if usage:
                            yield self._format_data(model=model, usage=usage)
                        # finish
                        finish_reason = choice.get("finish_reason") or ""
                        if finish_reason:
                            yield self._format_data(model=model, if_finished=True)
        except Exception as err:
            logger.exception("[OAIProReasoning] failed of %s", err)
            yield self._format_data(model=model, content=str(err), if_finished=True)

    async def _build_payload(self, body: dict, user_valves: UserValves) -> Tuple[str, dict]:
        # build messages
        messages = body["messages"]
        # build body
        model = body["model"].split(".", 1)[1]
        data = {
            "model": model,
            "messages": messages,
            **(
                {
                    "reasoning": {
                        "effort": user_valves.reasoning_effort,
                        "exclude": False,
                    },
                }
                if self.valves.enable_reasoning
                else {}
            ),
            "stream": True,
        }
        # other parameters
        allowed_params = [k for k in self.valves.allow_params.split(",") if k]
        for key, val in body.items():
            if key in allowed_params:
                data[key] = val
        payload = {"method": "POST", "url": "/chat/completions", "json": data}
        return model, payload

    def _format_data(
        self,
        model: Optional[str] = "",
        content: Optional[str] = "",
        usage: Optional[dict] = None,
        if_finished: bool = False,
    ) -> str:
        data = {
            "id": f"chat.{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "choices": [],
            "created": int(time.time()),
            "model": model,
        }
        if content:
            data["choices"] = [
                {
                    "finish_reason": "stop" if if_finished else "",
                    "index": 0,
                    "delta": {
                        "content": content,
                    },
                }
            ]
        if usage:
            data["usage"] = usage
        return f"data: {json.dumps(data)}\n\n"
