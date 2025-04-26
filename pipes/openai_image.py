"""
title: OpenAI Image
author: OVINC CN
author_url: https://www.ovinc.cn
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.0.1
licence: MIT
"""

import base64
import io
import logging
import uuid
from typing import AsyncGenerator, AsyncIterable, List

from fastapi import Request, UploadFile
from httpx import Client
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.users import UserModel, Users
from open_webui.routers.files import get_file_content_by_id, upload_file
from openai import OpenAI
from openai._types import FileTypes
from pydantic import BaseModel, Field
from starlette.datastructures import Headers

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MAIN"])


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://api.openai.com/v1", description="base url")
        api_key: str = Field(default="", description="api key")
        num_of_images: int = Field(default=1, description="number of images", ge=1, le=10)
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
    ) -> AsyncGenerator:
        user = Users.get_user_by_id(__user__["id"])
        try:
            async for line in self._pipe(body=body, user=user, __request__=__request__):
                yield line
        except Exception as err:
            logger.exception("[OpenAIImagePipe] failed of %s", err)
            raise err

    async def _pipe(self, body: dict, user: UserModel, __request__: Request) -> AsyncIterable:
        # payload
        model = body["model"].split(".", 1)[1]
        payload = {"image": None, "prompt": ""}

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
                        payload["image"] = await self._get_image_content(user, item)
                        continue
                    payload["prompt"] += f"\n{message_content}"
            # list content
            elif isinstance(message_content, list):
                for content in message_content:
                    if content["type"] == "text":
                        payload["prompt"] += f"\n{content['text']}"
                        continue
                    if content["type"] == "image_url":
                        image_url = content["image_url"]["url"]
                        header, encoded = image_url.split(",", 1)
                        mime_type = header.split(";")[0].split(":")[1]
                        file_name = f"{uuid.uuid4().hex}.{mime_type.split('/')[-1]}"
                        image_bytes = base64.b64decode(encoded.encode())
                        payload["image"] = (
                            file_name,
                            image_bytes,
                            mime_type,
                            {"content-type": mime_type},
                        )
            else:
                raise TypeError("message content invalid")

        # call client
        client = OpenAI(
            base_url=self.valves.base_url,
            api_key=self.valves.api_key,
            http_client=Client(proxy=self.valves.proxy, trust_env=True),
        )
        if payload["image"]:
            response = client.images.edit(
                image=payload["image"],
                prompt=payload["prompt"],
                model=model,
                n=self.valves.num_of_images,
                timeout=self.valves.timeout,
            )
        else:
            response = client.images.generate(
                prompt=payload["prompt"],
                model=model,
                n=self.valves.num_of_images,
            )

        results = []
        for item in response.data:
            results.append(
                self._upload_image(
                    __request__=__request__,
                    user=user,
                    image_data=item.b64_json,
                    mime_type="image/png",
                )
            )

        # format response data
        usage = getattr(response, "usage", None)
        if isinstance(usage, BaseModel):
            usage = usage.model_dump(exclude_none=True)

        # response
        yield "\n\n".join(results)
        yield {"usage": usage}

    def _upload_image(self, __request__: Request, user: UserModel, image_data: str, mime_type: str) -> str:
        file_item = upload_file(
            request=__request__,
            file=UploadFile(
                file=io.BytesIO(base64.b64decode(image_data)),
                filename=f"generated-image-{uuid.uuid4().hex}.png",
                headers=Headers({"content-type": mime_type}),
            ),
            user=user,
            file_metadata={"mime_type": mime_type},
        )
        image_url = __request__.app.url_path_for("get_file_content_by_id", id=file_item.id)
        return f"![openai-image-{file_item.id}]({image_url})"

    async def _get_image_content(self, user: UserModel, markdown_string: str) -> FileTypes:
        file_id = markdown_string.split("![openai-image-")[1].split("]")[0]
        file_response = await get_file_content_by_id(id=file_id, user=user)
        return open(file_response.path, "rb")
