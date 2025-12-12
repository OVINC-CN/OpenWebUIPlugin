"""
title: Gemini Deep Research
description: Deep Research with Gemini
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.1
licence: MIT
"""

import asyncio
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

INTERACTION_ID_LINE_PREFIX = "[interaction_id] "


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(
            default="https://generativelanguage.googleapis.com/v1beta",
            title="Base URL",
        )
        api_key: str = Field(default="", title="API Key")
        allow_params: Optional[str] = Field(
            default="",
            title="透传参数",
            description="允许配置的参数，使用英文逗号分隔，例如 temperature",
        )
        timeout: int = Field(default=300, title="请求超时时间 (秒)")
        task_timeout: int = Field(default=600, title="任务超时时间 (秒)")
        check_interval: int = Field(default=3, title="任务状态检查间隔 (秒)")
        proxy: Optional[str] = Field(default=None, title="代理地址")
        agent: str = Field(
            default="deep-research-pro-preview-12-2025",
            title="Agent",
            description="使用英文逗号分隔多个Agent",
        )

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
        return [{"id": model, "name": model} for model in self.valves.agent.split(",")]

    async def pipe(
        self,
        body: dict,
        __user__: dict,
        __request__: Request,
    ) -> StreamingResponse:
        return StreamingResponse(self._pipe(body=body, __user__=__user__, __request__=__request__))

    async def _pipe(self, body: dict, __user__: dict, __request__: Request) -> AsyncIterable:
        model, payload = await self._build_payload(body=body)
        last_status = {"last_status": ""}
        # call client
        async with httpx.AsyncClient(
            headers={"x-goog-api-key": self.valves.api_key},
            proxy=self.valves.proxy or None,
            trust_env=True,
            timeout=self.valves.timeout,
        ) as client:
            response = await client.request(**payload)
            # check resp
            if response.status_code != 200:
                logger.error(
                    "[GeminiDeepResearchPipe] response invalid with %d: %s",
                    response.status_code,
                    response.text,
                )
                response.raise_for_status()
                return
            # parse resp
            resp_data = response.json()
            yield self._format_data(
                is_stream=True,
                model=model,
                content=f"{INTERACTION_ID_LINE_PREFIX}{resp_data['id']}\n\n",
            )
            yield self._task_status(last_status, resp_data)
        # loop for results
        end_time = time.time() + self.valves.task_timeout
        url = self.valves.base_url.rstrip("/") + f"/interactions/{resp_data['id']}"
        async with httpx.AsyncClient(
            headers={"x-goog-api-key": self.valves.api_key},
            proxy=self.valves.proxy or None,
            trust_env=True,
            timeout=self.valves.timeout,
        ) as client:
            while time.time() < end_time:
                try:
                    response = await client.get(url)
                except httpx.RequestError as e:
                    logger.error(f"[GeminiDeepResearchPipe] request error: {e}")
                    await asyncio.sleep(self.valves.check_interval)
                    continue
                # check resp
                if response.status_code != 200:
                    logger.error(
                        "[GeminiDeepResearchPipe] response invalid with %d: %s",
                        response.status_code,
                        response.text,
                    )
                    response.raise_for_status()
                    return
                # parse resp
                resp_data = response.json()
                yield self._task_status(last_status, resp_data)
                # format content
                for output in resp_data.get("outputs", []) or []:
                    match output["type"]:
                        case "text":
                            yield self._format_data(is_stream=True, model=model, content=output["text"])
                        case "image":
                            image_data = output["data"]
                            mime_type = output["mime_type"]
                            image_url = f"data:{mime_type};base64,{image_data}"
                            yield self._format_data(
                                is_stream=True,
                                model=model,
                                content=f"![image]({image_url})",
                            )
                        case _:
                            continue
                # check finished
                if self._task_finished(last_status["last_status"]):
                    # format usage data
                    usage_metadata = resp_data.get("usage", None) or {}
                    usage = {
                        "prompt_tokens": (usage_metadata.pop("total_input_tokens", 0) if usage_metadata else 0),
                        "completion_tokens": (usage_metadata.pop("total_output_tokens", 0) if usage_metadata else 0),
                        "total_tokens": (usage_metadata.pop("total_tokens", 0) if usage_metadata else 0),
                        "prompt_token_details": {
                            "cached_tokens": (usage_metadata.get("total_cached_tokens", 0) if usage_metadata else 0)
                        },
                        "metadata": usage_metadata or {},
                    }
                    if usage_metadata and "total_tool_use_tokens" in usage_metadata:
                        usage["prompt_tokens"] += usage_metadata["total_tool_use_tokens"]
                    if usage_metadata and "total_reasoning_tokens" in usage_metadata:
                        usage["completion_tokens"] += usage_metadata["total_reasoning_tokens"]
                    if usage["prompt_tokens"] + usage["completion_tokens"] != usage["total_tokens"]:
                        usage["completion_tokens"] = usage["total_tokens"] - usage["prompt_tokens"]
                    yield self._format_data(is_stream=True, model=model, usage=usage)
                    return
                await asyncio.sleep(self.valves.check_interval)
            raise TimeoutError("[GeminiDeepResearchPipe] task timeout")

    async def _build_payload(self, body: dict) -> Tuple[str, dict]:
        # payload
        model = body["model"].split(".", 1)[1]
        all_contents = []

        # extract interaction_id
        interaction_id = ""
        for message in body["messages"]:
            content = message["content"]
            if not isinstance(content, str):
                continue
            interaction_id_line = content.split("\n", 1)[0]
            if interaction_id_line.startswith(INTERACTION_ID_LINE_PREFIX):
                interaction_id = interaction_id_line[len(INTERACTION_ID_LINE_PREFIX) :].strip()

        # read messages
        message = body["messages"][-1]
        # parse content
        message_content = message["content"]
        # str content
        if isinstance(message_content, str):
            all_contents.append({"type": "text", "text": message_content})
        # list content
        elif isinstance(message_content, list):
            for content in message_content:
                if content["type"] == "text":
                    all_contents.append({"type": "text", "text": content["text"]})
                elif content["type"] == "image_url":
                    image_url = content["image_url"]["url"]
                    header, encoded = image_url.split(",", 1)
                    mime_type = header.split(";")[0].split(":")[1]
                    all_contents.append({"type": "image", "data": encoded, "mime_type": mime_type})
                else:
                    raise TypeError("message content invalid")
        else:
            raise TypeError("message content invalid")

        # separate system instructions
        system_instruction = ""
        for message in body["messages"]:
            if message["role"] == "system":
                system_instruction += message["content"]
                continue
        if system_instruction != "":
            all_contents.insert(0, {"type": "text", "text": system_instruction})

        # other parameters
        extra_data = {}
        allowed_params = [k for k in self.valves.allow_params.split(",") if k]
        for key, val in body.items():
            if key in allowed_params:
                extra_data[key] = val

        # init payload
        payload = {
            "method": "POST",
            "url": self.valves.base_url.rstrip("/") + "/interactions",
            "json": {
                **extra_data,
                "agent": model,
                "input": all_contents,
                "background": True,
            },
        }
        if interaction_id != "":
            payload["json"]["previous_interaction_id"] = interaction_id
        logger.info("[GeminiDeepResearchPipe] payload: %s", payload)

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

    def _task_status(self, last_status: dict, resp_data: dict) -> str:
        new_status = str(resp_data["status"]).capitalize()
        if last_status["last_status"] == new_status:
            return ""
        last_status["last_status"] = new_status
        data = {
            "event": {
                "type": "status",
                "data": {
                    "description": f"Deep Research Status: {' '.join([i.capitalize() for i in new_status.split('_')])}",
                    "done": self._task_finished(new_status),
                },
            }
        }
        return f"data: {json.dumps(data)}\n\n"

    def _task_finished(self, task_status: str) -> bool:
        return task_status.lower() in ["completed", "failed", "cancelled"]
