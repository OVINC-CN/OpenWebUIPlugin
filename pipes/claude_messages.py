"""
title: Claude Messages
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.1.0
licence: MIT
"""

import json
import logging
import time
import uuid
from typing import AsyncIterable, Optional, Tuple

import httpx
from fastapi import Request
from httpx import Response
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel("INFO")


class APIException(Exception):
    def __init__(self, status: int, content: str, response: Response):
        self._status = status
        self._content = content
        self._response = response

    def __str__(self) -> str:
        # error msg
        try:
            return json.loads(self._content)["error"]["message"]
        except Exception:
            pass
        # build in error
        try:
            self._response.raise_for_status()
        except Exception as err:
            return str(err)
        return "Unknown API error"


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://api.anthropic.com/v1", title="Base URL")
        api_key: str = Field(default="", title="API Key")
        allow_params: Optional[str] = Field(
            default="", title="透传参数", description="允许配置的参数，使用英文逗号分隔，例如 temperature"
        )
        timeout: int = Field(default=600, title="请求超时时间（秒）")
        proxy: Optional[str] = Field(default="", title="代理地址")
        models: str = Field(default="claude-sonnet-4-5", title="模型", description="使用英文逗号分隔多个模型")
        beta_tools: str = Field(
            default="code_execution_20250825/code-execution-2025-08-25,web_fetch_20250910/web-fetch-2025-09-10",
            title="Beta工具和请求头",
            description="使用英文逗号分隔多个工具，使用/分隔工具和请求头",
        )

    class UserValves(BaseModel):
        max_tokens: int = Field(default=64000, title="最大响应Token数")
        enable_thinking: bool = Field(default=True, title="启用思考")
        thinking_budget: int = Field(default=10240, title="思考预算")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": model, "name": model} for model in self.valves.models.split(",") if model]

    async def pipe(self, body: dict, __user__: dict, __request__: Request) -> StreamingResponse:
        return StreamingResponse(self.__stream_pipe(body=body, __user__=__user__, __request__=__request__))

    async def __stream_pipe(self, body: dict, __user__: dict, __request__: Request) -> AsyncIterable:
        model, payload = await self._build_payload(body=body, user_valves=__user__["valves"])
        # call client
        async with httpx.AsyncClient(
            base_url=self.valves.base_url,
            headers={"anthropic-version": "2023-06-01", "X-Api-Key": self.valves.api_key},
            proxy=self.valves.proxy or None,
            trust_env=True,
            timeout=self.valves.timeout,
        ) as client:
            async with client.stream(**payload) as response:
                if response.status_code != 200:
                    text = ""
                    async for line in response.aiter_lines():
                        text += line  # pylint: disable=R1713
                    logger.error("response invalid with %d: %s", response.status_code, text)
                    raise APIException(status=response.status_code, content=text, response=response)
                is_thinking = False
                running_tool = ""
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
                        case "content_block_start":
                            if line["content_block"].get("type") == "thinking":
                                is_thinking = True
                            if line["content_block"].get("type") == "server_tool_use":
                                running_tool = line["content_block"].get("name", "")
                                data = {
                                    "event": {
                                        "type": "status",
                                        "data": {
                                            "description": f"{running_tool} running",
                                            "done": False,
                                        },
                                    }
                                }
                                yield f"data: {json.dumps(data)}\n\n"
                        case "content_block_stop":
                            if is_thinking:
                                is_thinking = False
                            if running_tool:
                                data = {
                                    "event": {
                                        "type": "status",
                                        "data": {
                                            "description": f"{running_tool} finished",
                                            "done": True,
                                        },
                                    }
                                }
                                running_tool = ""
                                yield f"data: {json.dumps(data)}\n\n"
                        case "content_block_delta":
                            delta = line["delta"]
                            yield self._format_stream_data(
                                model=model,
                                reasoning_content=delta.get("thinking") or "",
                                content=delta.get("text") or "",
                            )
                        case "message_delta":
                            metadata = line.get("usage") or None
                            if not metadata:
                                continue
                            usage = {
                                "prompt_tokens": metadata.pop("input_tokens", 0),
                                "completion_tokens": metadata.pop("output_tokens", 0),
                                "prompt_token_details": {
                                    "cached_tokens": metadata.pop("cache_read_input_tokens", 0),
                                    "cache_creation_input_tokens": metadata.pop("cache_creation_input_tokens", 0),
                                },
                                "metadata": metadata,
                            }
                            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
                            yield self._format_stream_data(model=model, usage=usage, if_finished=True)

    async def _build_payload(self, body: dict, user_valves: UserValves, stream: bool = True) -> Tuple[str, dict]:
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
                        content.append({"type": "text", "text": item["text"]})
                    elif item["type"] == "image_url":
                        content.append(
                            {
                                "type": "image",
                                "source": {
                                    **(
                                        {
                                            "type": "url",
                                            "url": item["image_url"]["url"],
                                        }
                                        if item["image_url"]["url"].startswith("http")
                                        else {
                                            # data:image/png;base64,xxx
                                            "type": "base64",
                                            "data": item["image_url"]["url"].split(",", 1)[1],
                                            "media_type": (item["image_url"]["url"].split(";", 1)[0]).split(":", 1)[1],
                                        }
                                    )
                                },
                            }
                        )
                    else:
                        raise TypeError("Invalid message content type %s" % item["type"])
                messages.append({"role": message["role"], "content": content})
            else:
                raise TypeError("Invalid message content type %s" % type(message["content"]))

        # extract system prompt
        system_prompt = ""
        new_messages = []
        for message in messages:
            if message["role"] == "system":
                system_prompt += message["content"] + "\n"
                continue
            new_messages.append(message)
        system_prompt = system_prompt.strip()

        # build body
        data = {
            "model": model,
            "messages": new_messages,
            "max_tokens": user_valves.max_tokens,
            "thinking": {
                "type": "enabled" if user_valves.enable_thinking else "disabled",
                **({"budget_tokens": user_valves.thinking_budget} if user_valves.enable_thinking else {}),
            },
            "stream": stream,
        }
        if system_prompt:
            data["system"] = system_prompt

        # other parameters
        allowed_params = [k for k in self.valves.allow_params.split(",") if k]
        for key, val in body.items():
            if key in allowed_params:
                data[key] = val
        payload = {"method": "POST", "url": "/messages", "json": data}

        # check tools
        beta_headers = []
        beta_tools = [i.strip().split("/", 1) for i in self.valves.beta_tools.split(",") if i.strip()]
        if body.get("tools", []):
            payload["json"]["tools"] = body["tools"]
            for tool in body["tools"]:
                for beta_tool, header in beta_tools:
                    if beta_tool == tool.get("type"):
                        beta_headers.append(header)
        if beta_headers:
            payload["headers"] = {"anthropic-beta": ",".join(beta_headers)}

        return model, payload

    # pylint: disable=R0913,R0917
    def _format_stream_data(
        self,
        model: Optional[str] = "",
        content: Optional[str] = "",
        reasoning_content: Optional[str] = "",
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
        if content or reasoning_content:
            data["choices"] = [
                {
                    "finish_reason": "stop" if if_finished else "",
                    "index": 0,
                    "delta": {"content": content, "reasoning_content": reasoning_content},
                }
            ]
        if usage:
            data["usage"] = usage
        return f"data: {json.dumps(data)}\n\n"
