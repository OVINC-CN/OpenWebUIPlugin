"""
title: Gemini Chat
description: Text generation with Gemini
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.10
licence: MIT
"""

import json
import logging
import time
import uuid
from typing import AsyncIterable, Literal, Optional, Tuple

import httpx
from fastapi import Request
from httpx import Response
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MAIN"])


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
        base_url: str = Field(
            default="https://generativelanguage.googleapis.com/v1beta/models",
            title="Base URL",
        )
        api_key: str = Field(default="", title="API Key")
        allow_params: Optional[str] = Field(
            default="", title="透传参数", description="允许配置的参数，使用英文逗号分隔，例如 temperature"
        )
        enable_reasoning: bool = Field(default=True, title="展示思考内容")
        timeout: int = Field(default=600, title="请求超时时间 (秒)")
        proxy: Optional[str] = Field(default=None, title="代理地址")
        models: str = Field(default="gemini-2.5-pro", title="模型", description="使用英文逗号分隔多个模型")

    class UserValves(BaseModel):
        reasoning_effort: Literal["low", "medium", "high"] = Field(
            default="low", title="推理强度", description="适用 Gemini 3 系列"
        )
        thinking_budget: int = Field(default=512, title="思考预算", description="适用 Gemini 2.5 系列，-1 表示自动控制")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": model, "name": model} for model in self.valves.models.split(",")]

    async def pipe(
        self,
        body: dict,
        __user__: dict,
        __request__: Request,
    ) -> StreamingResponse:
        return StreamingResponse(self._pipe(body=body, __user__=__user__, __request__=__request__))

    async def _pipe(self, body: dict, __user__: dict, __request__: Request) -> AsyncIterable:
        model, payload = await self._build_payload(body=body, user_valves=__user__["valves"])
        # call client
        async with httpx.AsyncClient(
            headers={"x-goog-api-key": self.valves.api_key},
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
                    raise APIException(response.status_code, text, response)
                # parse resp
                is_thinking = self.valves.enable_reasoning
                if is_thinking:
                    yield self._format_data(is_stream=True, model=model, content="<think>")
                async for line in response.aiter_lines():
                    # format stream data
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:") or not line.startswith("data:"):
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    if isinstance(line, str):
                        line = json.loads(line)
                    for item in line["candidates"]:
                        content = item.get("content", {})
                        if not content:
                            yield self._format_data(is_stream=True, model=model, content=item.get("finishReason", ""))
                            continue
                        parts = content.get("parts", [])
                        if not parts:
                            yield self._format_data(is_stream=True, model=model, content=item.get("finishReason", ""))
                            continue
                        for part in parts:
                            # thinking content
                            if part.get("thought", False):
                                if is_thinking:
                                    yield self._format_data(is_stream=True, model=model, content=part["text"])
                            # no thinking content
                            else:
                                # stop thinking
                                if is_thinking and part.get("text"):
                                    is_thinking = False
                                    yield self._format_data(is_stream=True, model=model, content="</think>")
                                # text content
                                if part.get("text"):
                                    yield self._format_data(is_stream=True, model=model, content=part["text"])
                                # code content
                                if part.get("executableCode"):
                                    data = {
                                        "event": {
                                            "type": "status",
                                            "data": {
                                                "description": (
                                                    f"executableCode {part['executableCode'].get('language', '')}"
                                                ),
                                                "done": False,
                                            },
                                        }
                                    }
                                    yield f"data: {json.dumps(data)}\n\n"
                                if part.get("codeExecutionResult"):
                                    data = {
                                        "event": {
                                            "type": "status",
                                            "data": {
                                                "description": (
                                                    "codeExecutionResult "
                                                    f"{part['codeExecutionResult'].get('outcome', '')}"
                                                ),
                                                "done": True,
                                            },
                                        }
                                    }
                                    yield f"data: {json.dumps(data)}\n\n"
                    # format usage data
                    usage_metadata = line.get("usageMetadata", None) or {}
                    usage = {
                        "prompt_tokens": usage_metadata.pop("promptTokenCount", 0) if usage_metadata else 0,
                        "completion_tokens": usage_metadata.pop("candidatesTokenCount", 0) if usage_metadata else 0,
                        "total_tokens": usage_metadata.pop("totalTokenCount", 0) if usage_metadata else 0,
                        "prompt_token_details": {
                            "cached_tokens": (usage_metadata.get("cachedContentTokenCount", 0) if usage_metadata else 0)
                        },
                        "metadata": usage_metadata or {},
                    }
                    if usage_metadata and "toolUsePromptTokenCount" in usage_metadata:
                        usage["prompt_tokens"] += usage_metadata["toolUsePromptTokenCount"]
                    if usage_metadata and "thoughtsTokenCount" in usage_metadata:
                        usage["completion_tokens"] += usage_metadata["thoughtsTokenCount"]
                    if usage["prompt_tokens"] + usage["completion_tokens"] != usage["total_tokens"]:
                        usage["completion_tokens"] = usage["total_tokens"] - usage["prompt_tokens"]
                    yield self._format_data(is_stream=True, model=model, usage=usage)

    async def _build_payload(self, body: dict, user_valves: UserValves) -> Tuple[str, dict]:
        # payload
        model = body["model"].split(".", 1)[1]
        is_gemini_3_series = "gemini-3" in model
        all_contents = []

        # read messages
        for message in body["messages"]:
            # parse content
            role = message["role"]
            message_content = message["content"]
            # str content
            if isinstance(message_content, str):
                all_contents.append({"role": role, "parts": [{"text": message_content}]})
            # list content
            elif isinstance(message_content, list):
                tmp_content = {"role": role, "parts": []}
                for content in message_content:
                    if content["type"] == "text":
                        tmp_content["parts"].append({"text": content["text"]})
                    elif content["type"] == "image_url":
                        image_url = content["image_url"]["url"]
                        header, encoded = image_url.split(",", 1)
                        mime_type = header.split(";")[0].split(":")[1]
                        tmp_content["parts"].append({"inline_data": {"mime_type": mime_type, "data": encoded}})
                    else:
                        raise TypeError("message content invalid")
                all_contents.append(tmp_content)
            else:
                raise TypeError("message content invalid")

        # separate system instructions
        contents = []
        system_instruction = {"parts": []}
        for content in all_contents:
            if content["role"] == "system":
                system_instruction["parts"].extend(content["parts"])
                continue
            if content["role"] == "assistant":
                content["role"] = "model"
            contents.append(content)

        # get thinking budget
        think_config = {"includeThoughts": True}
        if is_gemini_3_series:
            think_config["thinkingLevel"] = user_valves.reasoning_effort
        else:
            think_config["thinkingBudget"] = user_valves.thinking_budget

        # other parameters
        extra_data = {}
        allowed_params = [k for k in self.valves.allow_params.split(",") if k]
        for key, val in body.items():
            if key in allowed_params:
                extra_data[key] = val

        # init payload
        payload = {
            "method": "POST",
            "url": f"{self.valves.base_url}/{model}:streamGenerateContent?alt=sse",
            "json": {
                **extra_data,
                **({"system_instruction": system_instruction} if system_instruction["parts"] else {}),
                "contents": contents,
                "generationConfig": {"thinkingConfig": think_config},
            },
        }

        # check tools
        if body.get("tools", []):
            payload["json"]["tools"] = body["tools"]

        return model, payload

    def _format_data(
        self,
        is_stream: bool,
        model: Optional[str] = "",
        content: Optional[str] = "",
        usage: Optional[dict] = None,
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
                    "finish_reason": "stop",
                    "index": 0,
                    "delta" if is_stream else "message": {
                        "content": content,
                    },
                }
            ]
        if usage:
            data["usage"] = usage
        return f"data: {json.dumps(data)}\n\n"
