"""
title: OpenAI Image
author: OVINC CN
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.3
licence: MIT
"""

import base64
import io
import json
import logging
import time
import uuid
from typing import AsyncIterable, List, Literal, Optional

import httpx
from fastapi import Request, UploadFile
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.users import UserModel, Users
from open_webui.routers.files import get_file_content_by_id, upload_file
from openai._types import FileTypes
from pydantic import BaseModel, Field
from starlette.datastructures import Headers
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MAIN"])


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://api.openai.com/v1", description="base url")
        api_key: str = Field(default="", description="api key")
        num_of_images: int = Field(default=1, description="number of images", ge=1, le=10)
        quality: Literal["low", "medium", "high", "auto"] = Field(
            default="auto", description="the quality of the image that will be generated"
        )
        size: Literal["1024x1024", "1536x1024", "1024x1536", "auto"] = Field(default="auto", description="image size")
        timeout: int = Field(default=600, description="image timeout")
        proxy: str = Field(default="", description="proxy url")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> List[dict]:
        return [{"id": "gpt-image-1", "name": "GPT Image 1"}]

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
                for item in response["data"]:
                    results.append(
                        self._upload_image(
                            __request__=__request__,
                            user=user,
                            image_data=item["b64_json"],
                            mime_type="image/png",
                        )
                    )

                # format response data
                usage = response.get("usage", None)

                # response
                content = "\n\n".join(results)
                if body.get("stream"):
                    yield self._format_data(is_stream=True, model=model, content=content, usage=None)
                    yield self._format_data(is_stream=True, model=model, content=None, usage=usage)
                else:
                    yield self._format_data(is_stream=False, model=model, content=content, usage=usage)
        except Exception as err:
            logger.exception("[OpenAIImagePipe] failed of %s", err)
            yield self._format_data(is_stream=False, content=str(err))

    def _upload_image(self, __request__: Request, user: UserModel, image_data: str, mime_type: str) -> str:
        file_item = upload_file(
            request=__request__,
            file=UploadFile(
                file=io.BytesIO(base64.b64decode(image_data)),
                filename=f"generated-image-{uuid.uuid4().hex}.png",
                headers=Headers({"content-type": mime_type}),
            ),
            user=user,
            metadata={"mime_type": mime_type},
        )
        image_url = __request__.app.url_path_for("get_file_content_by_id", id=file_item.id)
        return f"![openai-image-{file_item.id}]({image_url})"

    async def _get_image_content(self, user: UserModel, markdown_string: str) -> FileTypes:
        file_id = markdown_string.split("![openai-image-")[1].split("]")[0]
        file_response = await get_file_content_by_id(id=file_id, user=user)
        return open(file_response.path, "rb")

    async def _build_payload(self, user: UserModel, body: dict) -> (str, dict):
        # payload
        model = body["model"].split(".", 1)[1]
        data = {
            "image": [],
            "prompt": "",
            "n": self.valves.num_of_images,
            "model": model,
            "quality": self.valves.quality,
            "size": self.valves.size,
        }

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
                    if item.startswith("![openai-image-"):
                        data["image"].append(await self._get_image_content(user, item))
                        continue
                    data["prompt"] += f"\n{message_content}"
            # list content
            elif isinstance(message_content, list):
                for content in message_content:
                    if content["type"] == "text":
                        data["prompt"] += f"\n{content['text']}"
                        continue
                    if content["type"] == "image_url":
                        image_url = content["image_url"]["url"]
                        header, encoded = image_url.split(",", 1)
                        mime_type = header.split(";")[0].split(":")[1]
                        file_name = f"{uuid.uuid4().hex}.{mime_type.split('/')[-1]}"
                        image_bytes = base64.b64decode(encoded.encode())
                        data["image"].append(
                            (
                                file_name,
                                image_bytes,
                                mime_type,
                                {"content-type": mime_type},
                            )
                        )
            else:
                raise TypeError("message content invalid")

        # init payload
        if data["image"]:
            files = data.pop("image")
            payload = {"url": "/images/edits", "files": [("image[]", file) for file in files], "data": data}
        else:
            data.pop("image", None)
            payload = {"url": "/images/generations", "json": data}

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
