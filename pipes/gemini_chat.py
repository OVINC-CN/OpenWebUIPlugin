"""
title: Gemini Chat
description: Text generation with Gemini
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
        base_url: str = Field(
            default="https://generativelanguage.googleapis.com/v1beta/models",
            description="base url",
        )
        api_key: str = Field(default="", description="api key")
        thinking_budget: int = Field(default=-1, description="thinking budget")
        timeout: int = Field(default=600, description="timeout")
        proxy: Optional[str] = Field(default=None, description="proxy url")
        models: str = Field(default="gemini-2.5-pro", description="available models, comma separated")

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
        model, payload = await self._build_payload(body=body)
        try:
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
                        response.raise_for_status()
                        return
                    # parse resp
                    is_thinking = True
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
                                yield self._format_data(
                                    is_stream=True, model=model, content=item.get("finishReason", "")
                                )
                                continue
                            parts = content.get("parts", [])
                            if not parts:
                                yield self._format_data(
                                    is_stream=True, model=model, content=item.get("finishReason", "")
                                )
                                continue
                            for part in parts:
                                if part.get("thought", False):
                                    yield self._format_data(is_stream=True, model=model, content=part["text"])
                                else:
                                    if is_thinking:
                                        is_thinking = False
                                        yield self._format_data(is_stream=True, model=model, content="</think>")
                                    yield self._format_data(is_stream=True, model=model, content=part["text"])
                        # format usage data
                        usage_metadata = line.get("usageMetadata", None)
                        usage = {
                            "prompt_tokens": usage_metadata.get("promptTokenCount", 0) if usage_metadata else 0,
                            "completion_tokens": usage_metadata.get("candidatesTokenCount", 0) if usage_metadata else 0,
                            "total_tokens": usage_metadata.get("totalTokenCount", 0) if usage_metadata else 0,
                            "prompt_token_details": (
                                usage_metadata.get("promptTokensDetails", []) if usage_metadata else []
                            ),
                            "completion_token_details": {
                                "thinking_tokens": usage_metadata.get("thoughtsTokenCount", 0)
                            },
                        }
                        if usage["prompt_tokens"] + usage["completion_tokens"] != usage["total_tokens"]:
                            usage["completion_tokens"] = usage["total_tokens"] - usage["prompt_tokens"]
                        yield self._format_data(is_stream=True, model=model, usage=usage)

        except Exception as err:
            logger.exception("[GeminiChatPipe] failed of %s", err)
            yield self._format_data(is_stream=False, content=str(err))

    async def _build_payload(self, body: dict) -> Tuple[str, dict]:
        # payload
        model = body["model"].split(".", 1)[1]
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

        # init payload
        payload = {
            "method": "POST",
            "url": f"{self.valves.base_url}/{model}:streamGenerateContent?alt=sse",
            "json": {
                **({"system_instruction": system_instruction} if system_instruction["parts"] else {}),
                "contents": contents,
                "generationConfig": {
                    "thinkingConfig": {"thinkingBudget": self.valves.thinking_budget, "includeThoughts": True}
                },
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
