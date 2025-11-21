"""
title: OpenAI Responses
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.6
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
        base_url: str = Field(default="https://api.openai.com/v1", description="base url")
        api_key: str = Field(default="", description="api key")
        enable_reasoning: bool = Field(default=True, description="enable reasoning")
        summary: Literal["auto", "concise", "detailed"] = Field(default="auto", description="summary type")
        allow_params: Optional[str] = Field(default="", description="allowed parameters, comma separated")
        timeout: int = Field(default=600, description="timeout")
        proxy: Optional[str] = Field(default="", description="proxy url")
        models: str = Field(default="gpt-5", description="available models, comma separated")

    class UserValves(BaseModel):
        reasoning_effort: Literal["low", "medium", "high"] = Field(default="low", description="reasoning effort")

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
                            case "response.reasoning_summary_text.delta":
                                if is_thinking:
                                    yield self._format_data(model=model, content=line["delta"])
                            case "response.output_text.delta":
                                if is_thinking:
                                    is_thinking = False
                                    yield self._format_data(model=model, content="</think>")
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

    async def _build_payload(self, body: dict, user_valves: UserValves) -> Tuple[str, dict]:
        model = body["model"].split(".", 1)[1]

        # build messages
        messages = []
        for message in body["messages"]:
            if isinstance(message["content"], str):
                messages.append({"content": message["content"], "role": message["role"]})
            elif isinstance(message["content"], list):
                content = []
                for item in message["content"]:
                    if item["type"] == "text":
                        content.append({"type": "input_text", "text": item["text"]})
                    elif item["type"] == "image_url":
                        content.append(
                            {
                                "type": "input_image",
                                "image_url": item["image_url"]["url"],
                            }
                        )
                    else:
                        raise TypeError("Invalid message content type %s", item["type"])
                messages.append({"role": message["role"], "content": content})
            else:
                raise TypeError("Invalid message content type %s", type(message["content"]))

        # reasoning
        reasoning_effort = user_valves.reasoning_effort
        if "5-pro" in model or "5.1-pro" in model:
            reasoning_effort = "high"

        # build body
        data = {
            "model": model,
            "input": messages,
            "reasoning": {
                "effort": reasoning_effort,
                "summary": self.valves.summary,
            },
            "stream": True,
            "store": False,
        }
        # max tokens
        if "max_completion_tokens" in body:
            data["max_output_tokens"] = body["max_completion_tokens"]
        elif "max_tokens" in body:
            data["max_output_tokens"] = body["max_tokens"]
        # other parameters
        allowed_params = [k for k in self.valves.allow_params.split(",") if k]
        for key, val in body.items():
            if key in allowed_params:
                data[key] = val
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
