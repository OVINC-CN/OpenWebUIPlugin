"""
title: OpenAI Deep Research API
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.2
licence: MIT
"""

import json
import logging
import time
import uuid
from typing import AsyncIterable, Literal, Optional

import httpx
from fastapi import Request
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MAIN"])


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://api.openai.com/v1", description="base url")
        api_key: str = Field(default="", description="api key")
        reasoning_effort: Literal["medium", "high"] = Field(default="medium", description="reasoning effort")
        enable_code_interpreter: bool = Field(default=True, description="code interpreter")
        timeout: int = Field(default=600, description="timeout")
        proxy: str = Field(default="", description="proxy url")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [
            {"id": "o3-deep-research", "name": "o3-deep-research"},
            {"id": "o4-mini-deep-research", "name": "o4-mini-deep-research"},
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
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        if line.startswith("event:") or not line.startswith("data:"):
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        if isinstance(line, str):
                            line = json.loads(line)
                        match line.get("type"):
                            case "response.output_text.delta":
                                yield self._format_data(model=model, content=line["delta"])
                            case "response.completed":
                                yield self._format_data(
                                    model=model, content="", usage=line["response"]["usage"], if_finished=True
                                )
                            case _:
                                event_type = line["type"]
                                if event_type.endswith("in_progress") or event_type.endswith("completed"):
                                    event_type_split = event_type.split(".")[1:]
                                    if len(event_type_split) == 2:
                                        data = {
                                            "event": {
                                                "type": "status",
                                                "data": {
                                                    "description": " ".join(event_type_split),
                                                    "done": event_type_split[1] == "completed",
                                                },
                                            }
                                        }
                                        yield f"data: {json.dumps(data)}\n\n"
        except Exception as err:
            logger.exception("[OpenAIImagePipe] failed of %s", err)
            yield self._format_data(model=model, content=str(err), if_finished=True)

    async def _build_payload(self, body: dict) -> (str, dict):
        model = body["model"].split(".", 1)[1]
        tools = [{"type": "web_search_preview"}]
        if self.valves.enable_code_interpreter:
            tools.append({"type": "code_interpreter", "container": {"type": "auto"}})
        data = {
            "model": model,
            "input": body["messages"],
            "tools": tools,
            "reasoning": {"effort": body.get("reasoning_effort") or self.valves.reasoning_effort},
            "stream": True,
        }
        payload = {"method": "POST", "url": "/responses", "json": data}
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
