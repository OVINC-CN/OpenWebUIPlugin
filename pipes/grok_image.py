"""
title: Grok Image
description: Image generation with Grok
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.1.1
licence: MIT
"""

import base64
import io
import json
import logging
import time
import uuid
from typing import AsyncIterable, Literal, Optional, Tuple

import httpx
from fastapi import BackgroundTasks, Request, UploadFile
from httpx import Response
from open_webui.env import GLOBAL_LOG_LEVEL
from open_webui.models.users import UserModel, Users
from open_webui.routers.files import get_file_content_by_id, upload_file
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(GLOBAL_LOG_LEVEL)


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
        base_url: str = Field(default="https://api.x.ai/v1", title="Base URL")
        api_key: str = Field(default="", title="API Key")
        num_of_images: int = Field(default=1, title="图片数量", ge=1, le=10)
        timeout: int = Field(default=600, title="请求超时时间 (秒)")
        proxy: Optional[str] = Field(default="", title="代理地址")
        models: str = Field(default="grok-imagine-image-pro", title="模型", description="使用英文逗号分隔多个模型")

    class UserValves(BaseModel):
        enable_nsfw: bool = Field(default=False, title="是否启用NSFW内容")
        is_kids_mode: bool = Field(default=False, title="是否启用儿童模式")
        resolution: Literal["1k", "2k"] = Field(default="1k", title="图片分辨率")
        quality: Literal["low", "medium", "high"] = Field(default="medium", title="图片质量")
        aspect_ratio: Literal[
            "1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2", "9:19.5", "19.5:9", "9:20", "20:9", "1:2", "2:1", "auto"
        ] = Field(default="auto", title="图片比例")

    def __init__(self):
        self.valves = self.Valves()
        self.user_valves = self.UserValves()

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
        user = Users.get_user_by_id(__user__["id"])
        model, payload = await self._build_payload(user=user, body=body, user_valves=__user__["valves"])
        # call client
        async with httpx.AsyncClient(
            base_url=self.valves.base_url,
            headers={"Authorization": f"Bearer {self.valves.api_key}"},
            proxy=self.valves.proxy or None,
            trust_env=True,
            timeout=self.valves.timeout,
        ) as client:
            response = await client.post(**payload)
            if response.status_code != 200:
                raise APIException(status=response.status_code, content=response.text, response=response)
            response = response.json()
            # upload image
            results = []
            for item in response["data"]:
                results.append(
                    self._upload_image(
                        __request__=__request__,
                        user=user,
                        image_data=item["b64_json"],
                        mime_type=item["mime_type"],
                    )
                )
            # format response data
            usage_metadata = response.get("usage", None) or {}
            usage = {
                "prompt_tokens": len(payload["json"].get("images") or []),
                "completion_tokens": len(results),
                "metadata": usage_metadata or {},
            }
            usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
            # response
            content = "\n\n".join(results)
            if body.get("stream"):
                yield self._format_data(is_stream=True, model=model, content=content, usage=None)
                yield self._format_data(is_stream=True, model=model, content=None, usage=usage)
            else:
                yield self._format_data(is_stream=False, model=model, content=content, usage=usage)

    def _upload_image(self, __request__: Request, user: UserModel, image_data: str, mime_type: str) -> str:
        file_item = upload_file(
            request=__request__,
            background_tasks=BackgroundTasks(),
            file=UploadFile(
                file=io.BytesIO(base64.b64decode(image_data)),
                filename=f"generated-image-{uuid.uuid4().hex}.png",
                headers=Headers({"content-type": mime_type}),
            ),
            process=False,
            user=user,
            metadata={"mime_type": mime_type},
        )
        image_url = __request__.app.url_path_for("get_file_content_by_id", id=file_item.id)
        return f"![grok-image-{file_item.id}]({image_url})"

    async def _get_image_content(self, user: UserModel, markdown_string: str):
        file_id = markdown_string.split("![grok-image-")[1].split("]")[0]
        file_response = await get_file_content_by_id(id=file_id, user=user)
        return open(file_response.path, "rb")

    async def _build_payload(self, user: UserModel, body: dict, user_valves: UserValves) -> Tuple[str, dict]:
        # payload
        model = body["model"].split(".", 1)[1]
        images = []
        prompt = ""

        # read messages
        messages = body["messages"]
        if len(messages) >= 2:
            messages = messages[-2:]
        for message in messages:
            # ignore system message
            if message["role"] == "system":
                continue
            # parse content
            message_content = message["content"]
            # str content
            if isinstance(message_content, str):
                for item in message_content.split("\n"):
                    if not item:
                        continue
                    if item.startswith("![grok-image-"):
                        file = await self._get_image_content(user, item)
                        images.append({"url": f"data:image/jpeg;base64,{base64.b64encode(file.read()).decode()}"})
                        continue
                    prompt = item
            # list content
            elif isinstance(message_content, list):
                for content in message_content:
                    if content["type"] == "text":
                        prompt = content["text"]
                        continue
                    if content["type"] == "image_url":
                        image_url = content["image_url"]["url"]
                        images.append({"url": image_url})
            else:
                raise TypeError("message content invalid")

        # init payload
        payload = {
            "url": "/images/generations",
            "json": {
                "model": model,
                "prompt": (
                    f"<enable_nsfw>{str(user_valves.enable_nsfw).lower()}</enable_nsfw>"
                    f"<is_kids_mode>{str(user_valves.is_kids_mode).lower()}</is_kids_mode>\n"
                    f"{prompt}"
                ),
                "quality": user_valves.quality,
                "aspect_ratio": user_valves.aspect_ratio,
                "resolution": user_valves.resolution,
                "response_format": "b64_json",
                "n": self.valves.num_of_images,
            },
        }
        if images:
            payload["json"]["images"] = images
            payload["url"] = "/images/edits"

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
