"""
title: OAIPro Reasoning
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.1
licence: MIT
"""

import json
import logging
import time
import uuid
from typing import AsyncIterable, Optional, Tuple

import httpx
from fastapi import Request
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MAIN"])


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://api.oaipro.com/v1", description="Base URL")
        api_key: str = Field(default="", description="API Key")
        enable_reasoning: bool = Field(default=True, description="是否启用思考")
        reasoning_budget_tokens: int = Field(default=1024, description="思考预算Token数")
        max_tokens: int = Field(default=4096, description="最大响应Token数")
        allow_params: str = Field(
            default="", description="允许传入的参数，使用英文逗号分隔，其他 body 中的参数会被忽略"
        )
        timeout: int = Field(default=600, description="超时时间")
        proxy: Optional[str] = Field(default="", description="代理地址")
        models: str = Field(default="claude-sonnet-4-5-20250929", description="可用模型，使用英文逗号分隔")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [
            {"id": model.strip(), "name": model.strip()} for model in self.valves.models.split(",") if model.strip()
        ]

    async def pipe(self, body: dict, __user__: dict, __request__: Request) -> StreamingResponse:
        return StreamingResponse(self._pipe(body=body, __user__=__user__, __request__=__request__))

    async def _pipe(self, body: dict, __user__: dict, __request__: Request) -> AsyncIterable:
        model, payload = await self._build_payload(body=body)
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
                        reasoning_content = delta.get("reasoning_content") or ""
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

    async def _build_payload(self, body: dict) -> Tuple[str, dict]:
        # build messages
        messages = body["messages"]
        # build body
        model = body["model"].split(".", 1)[1]
        data = {
            "model": model,
            "messages": messages,
            **(
                {
                    "thinking": {
                        "type": "enabled",
                        "budget_tokens": body.get("reasoning_budget_tokens") or self.valves.reasoning_budget_tokens,
                    }
                }
                if self.valves.enable_reasoning
                else {}
            ),
            "stream": True,
            "max_tokens": body.get("max_tokens") or self.valves.max_tokens,
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
