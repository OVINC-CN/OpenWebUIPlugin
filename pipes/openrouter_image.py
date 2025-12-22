"""
title: OpenRouter Image
description: Image generation with OpenRouter API
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.2
licence: MIT
"""

import base64
import io
import json
import logging
import time
import uuid
from typing import AsyncIterable, Optional, Tuple

import httpx
from fastapi import BackgroundTasks, Request, UploadFile
from open_webui.env import GLOBAL_LOG_LEVEL
from open_webui.models.users import UserModel, Users
from open_webui.routers.files import get_file_content_by_id, upload_file
from openai._types import FileTypes
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(GLOBAL_LOG_LEVEL)


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://openrouter.ai/api/v1", description="base url")
        api_key: str = Field(default="", description="api key")
        timeout: int = Field(default=600, description="timeout")
        proxy: Optional[str] = Field(default="", description="proxy url")
        models: str = Field(
            default="google/gemini-2.5-flash-image-preview:free", description="available models, comma separated"
        )

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
        user = Users.get_user_by_id(__user__["id"])
        try:
            model, payload = await self._build_payload(user=user, body=body)
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
                    raise httpx.HTTPStatusError(
                        message=response.content.decode(), request=response.request, response=response
                    )
                response = response.json()

                # upload image
                results = []
                choices = response.get("choices", [])
                if not choices:
                    raise ValueError("no choices in response")
                choice = choices[0]
                finish_reason = choice.get("finish_reason", "")
                message = choice.get("message", {})
                if not message:
                    results.append(finish_reason)
                else:
                    content = message.get("content", "")
                    if content:
                        results.append(content)
                    images = message.get("images", [])
                    for image in images:
                        image_url = image["image_url"]["url"][5:]
                        mime_type, data = image_url.split(";", 1)
                        results.append(
                            self._upload_image(
                                __request__=__request__,
                                user=user,
                                image_data=data[7:],
                                mime_type=mime_type,
                            )
                        )

                # format response data
                usage = response.get("usage", {})

                # response
                content = "\n\n".join(results)
                if body.get("stream"):
                    yield self._format_data(is_stream=True, model=model, content=content, usage=None)
                    yield self._format_data(is_stream=True, model=model, content=None, usage=usage)
                else:
                    yield self._format_data(is_stream=False, model=model, content=content, usage=usage)
        except Exception as err:
            logger.exception("[OpenRouterImagePipe] failed of %s", err)
            yield self._format_data(is_stream=False, content=str(err))

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
        return f"![openrouter-image-{file_item.id}]({image_url})"

    async def _get_image_content(self, user: UserModel, markdown_string: str) -> FileTypes:
        file_id = markdown_string.split("![openrouter-image-")[1].split("]")[0]
        file_response = await get_file_content_by_id(id=file_id, user=user)
        return open(file_response.path, "rb")

    async def _build_payload(self, user: UserModel, body: dict) -> Tuple[str, dict]:
        # payload
        model = body["model"].split(".", 1)[1]
        tmp_messages = []

        # read messages
        messages = body["messages"]
        if len(messages) >= 2:
            messages = messages[-2:]
        for message in messages:
            # ignore system message
            if message["role"] == "system":
                tmp_messages.append(message)
                continue
            # parse content
            message_content = message["content"]
            # str content
            if isinstance(message_content, str):
                content = []
                for item in message_content.split("\n"):
                    if not item:
                        continue
                    if item.startswith("![openrouter-image-"):
                        file = await self._get_image_content(user, item)
                        content.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{base64.b64encode(file.read()).decode()}"},
                            }
                        )
                        continue
                    content.append({"type": "text", "text": item})
                tmp_messages.append({"role": message["role"], "content": content})
            # list content
            elif isinstance(message_content, list):
                tmp_messages.append(message)
            else:
                raise TypeError("message content invalid")

        # init payload
        payload = {"url": "/chat/completions", "json": {"model": model, "messages": tmp_messages}}

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
