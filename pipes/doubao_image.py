"""
title: Doubao Image
description: Image generation with Doubao Seedream 5.0
author: yuzukumo
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.1.1
licence: MIT
"""

import base64
import binascii
import json
import logging
import mimetypes
import time
import uuid
from typing import Any, AsyncIterable, List, Literal, Optional, Tuple

import httpx
from fastapi import Request
from httpx import Response
from open_webui.env import GLOBAL_LOG_LEVEL
from open_webui.models.users import UserModel
from open_webui.routers.files import get_file_content_by_id
from open_webui.routers.images import upload_image
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

logger = logging.getLogger(__name__)
logger.setLevel(GLOBAL_LOG_LEVEL)


class APIException(Exception):
    def __init__(self, status: int, content: str, response: Response):
        self._status = status
        self._content = content
        self._response = response

    def __str__(self) -> str:
        try:
            return json.loads(self._content).get("error", {}).get("message", self._content)
        except Exception:
            pass
        try:
            self._response.raise_for_status()
        except Exception as err:
            return str(err)
        return "Unknown API error"


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(
            default="https://ark.cn-beijing.volces.com/api/v3",
            title="Base URL",
        )
        api_key: str = Field(default="", title="API Key")
        timeout: int = Field(default=600, title="请求超时（秒）")
        proxy: str = Field(default="", title="代理地址")
        models: str = Field(
            default="doubao-seedream-5-0-260128,doubao-seedream-5-0-lite-260128",
            title="支持模型列表",
            description="多个模型用逗号分隔",
        )

    class UserValves(BaseModel):
        n: int = Field(default=1, title="输出张数", ge=1, le=10)
        size: str = Field(
            default="2K",
            title="尺寸",
            description="支持 2K、3K 或像素尺寸，例如 2048x2048",
        )
        output_format: Literal["png", "jpeg"] = Field(default="png", title="输出格式")
        watermark: bool = Field(default=False, title="AI 水印")
        enable_web_search: bool = Field(default=False, title="启用联网搜索")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> List[dict]:
        return [
            {"id": model.strip(), "name": model.strip()} for model in self.valves.models.split(",") if model.strip()
        ]

    async def pipe(
        self,
        body: dict,
        __user__: dict,
        __request__: Request,
        __metadata__: Optional[dict] = None,
    ) -> StreamingResponse:
        return StreamingResponse(
            self._pipe(body=body, __user__=__user__, __request__=__request__, __metadata__=__metadata__),
            media_type="text/event-stream",
        )

    async def _pipe(
        self,
        body: dict,
        __user__: dict,
        __request__: Request,
        __metadata__: Optional[dict] = None,
    ) -> AsyncIterable[str]:
        user = self._get_user(__user__)

        model, payload = await self._build_payload(user=user, body=body, user_valves=__user__.get("valves", {}))

        async with httpx.AsyncClient(
            base_url=self.valves.base_url,
            headers={"Authorization": f"Bearer {self.valves.api_key}"},
            proxy=self.valves.proxy or None,
            trust_env=True,
            timeout=self.valves.timeout,
        ) as client:
            response = await client.post(**payload)
            if response.status_code != 200:
                raise APIException(
                    status=response.status_code,
                    content=response.text,
                    response=response,
                )

            response_json = response.json()
            content, usage = await self._parse_response_content(
                response_json=response_json,
                user=user,
                __request__=__request__,
                metadata=__metadata__,
                output_format=payload["json"]["output_format"],
            )
            if body.get("stream"):
                yield self._format_data(is_stream=True, model=model, content=content, usage=None)
                if usage:
                    yield self._format_data(is_stream=True, model=model, content=None, usage=usage)
            else:
                yield self._format_data(is_stream=False, model=model, content=content, usage=usage)

    async def _build_payload(self, user: UserModel, body: dict, user_valves: Any) -> Tuple[str, dict]:
        user_valves = self._normalize_user_valves(user_valves)
        model = body["model"].split(".", 1)[1] if "." in body["model"] else body["model"]

        prompt, images = await self._parse_messages(user=user, body=body)

        if len(images) > 14:
            raise ValueError("豆包图片生成最多支持 14 张参考图。")
        if len(images) + user_valves.n > 15:
            raise ValueError("参考图数量 + 输出张数不能超过 15。")

        data = {
            "model": model,
            "prompt": prompt,
            "size": user_valves.size,
            "output_format": user_valves.output_format,
            "watermark": user_valves.watermark,
            "response_format": "b64_json",
        }

        if images:
            data["image"] = images[0] if len(images) == 1 else images

        if user_valves.n > 1:
            data["sequential_image_generation"] = "auto"
            data["sequential_image_generation_options"] = {"max_images": user_valves.n}

        if user_valves.enable_web_search:
            data["tools"] = [{"type": "web_search"}]

        payload = {
            "url": "/images/generations",
            "json": data,
        }
        return model, payload

    async def _parse_messages(self, user: UserModel, body: dict) -> Tuple[str, List[str]]:
        prompt_parts: List[str] = []
        images: List[str] = []

        messages = body.get("messages", [])
        if len(messages) > 6:
            messages = messages[-6:]

        for message in messages:
            role = message.get("role")
            if role == "system":
                continue

            allow_text = role != "assistant"
            content = message.get("content")

            if isinstance(content, str):
                for line in content.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("![") and "-image-" in line:
                        data_url = await self._get_image_data_url_from_markdown(user=user, markdown_string=line)
                        if data_url:
                            images.append(data_url)
                            continue
                    if allow_text:
                        prompt_parts.append(line)
                continue

            if isinstance(content, list):
                for item in content:
                    item_type = item.get("type")
                    if item_type == "text":
                        text = item.get("text", "").strip()
                        if text and allow_text:
                            prompt_parts.append(text)
                        continue

                    if item_type in {"image_url", "input_image"}:
                        image_url = self._extract_image_url(item)
                        if image_url:
                            images.append(image_url)
                        continue

                    raise TypeError("message content invalid")
                continue

            raise TypeError("message content invalid")

        prompt = "\n".join(prompt_parts).strip()
        if not prompt:
            prompt = body.get("prompt", "Please generate an image.")
        return prompt, images

    async def _parse_response_content(
        self,
        response_json: dict,
        user: UserModel,
        __request__: Request,
        metadata: Optional[dict],
        output_format: str,
    ) -> Tuple[str, Optional[dict]]:
        results: List[str] = []
        mime_type = "image/png" if output_format == "png" else "image/jpeg"
        for item in response_json.get("data", []):
            image_markdown = await self._render_response_item(
                item=item,
                user=user,
                __request__=__request__,
                metadata=metadata,
                fallback_mime_type=mime_type,
            )
            if image_markdown:
                results.append(image_markdown)

        if not results and response_json.get("error"):
            raise ValueError(self._extract_error_message(response_json["error"]) or "Unknown API error")

        if not results:
            raise ValueError("未解析到豆包图片响应")

        return "\n\n".join(results), response_json.get("usage")

    async def _render_response_item(
        self,
        item: dict,
        user: UserModel,
        __request__: Request,
        metadata: Optional[dict],
        fallback_mime_type: str,
    ) -> str:
        if not isinstance(item, dict):
            return ""

        b64_json = item.get("b64_json")
        image_url = item.get("url")
        mime_type = item.get("mime_type") or fallback_mime_type

        if b64_json:
            return await self._upload_image(
                __request__=__request__,
                user=user,
                image_data=b64_json,
                mime_type=mime_type,
                metadata=metadata,
            )

        if image_url:
            return f"![doubao-image-remote]({image_url})"

        return ""

    async def _upload_image(
        self,
        __request__: Request,
        user: UserModel,
        image_data: str,
        mime_type: str,
        metadata: Optional[dict],
    ) -> str:
        image_bytes = self._decode_base64_image(image_data)
        file_item, image_url = await upload_image(
            request=__request__,
            image_data=image_bytes,
            content_type=mime_type,
            metadata={"mime_type": mime_type, **(metadata or {})},
            user=user,
        )
        return f"![doubao-image-{file_item.id}]({image_url})"

    async def _get_image_data_url_from_markdown(self, user: UserModel, markdown_string: str) -> str:
        file_id = self._extract_file_id_from_markdown(markdown_string)
        if not file_id:
            return ""

        file_response = await get_file_content_by_id(id=file_id, user=user)
        with open(file_response.path, "rb") as file_content:
            image_bytes = file_content.read()

        mime_type = mimetypes.guess_type(file_response.path)[0] or "image/png"
        encoded = base64.b64encode(image_bytes).decode()
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _extract_image_url(item: dict) -> str:
        image_url = item.get("image_url", "")
        if isinstance(image_url, dict):
            image_url = image_url.get("url", "")
        return image_url if isinstance(image_url, str) else ""

    @staticmethod
    def _extract_file_id_from_markdown(markdown_string: str) -> str:
        try:
            alt_text = markdown_string.split("![", 1)[1].split("]", 1)[0]
            if "-image-" not in alt_text:
                return ""
            return alt_text.rsplit("-image-", 1)[1]
        except Exception:
            return ""

    @staticmethod
    def _extract_error_message(error: Any) -> str:
        if isinstance(error, dict):
            return error.get("message") or error.get("code") or ""
        if isinstance(error, str):
            return error
        return ""

    @staticmethod
    def _decode_base64_image(image_data: str) -> bytes:
        data = image_data.strip()
        if data.startswith("data:") and "," in data:
            data = data.split(",", 1)[1]

        data = "".join(data.split())

        try:
            decoded = base64.b64decode(data, validate=True)
        except (binascii.Error, ValueError):
            padding = len(data) % 4
            if padding:
                data = f"{data}{'=' * (4 - padding)}"
            decoded = base64.b64decode(data)

        if not decoded:
            raise ValueError("decoded image bytes is empty")
        return decoded

    @staticmethod
    def _normalize_user_valves(user_valves: Any) -> "Pipe.UserValves":
        if isinstance(user_valves, Pipe.UserValves):
            return user_valves
        if isinstance(user_valves, BaseModel):
            if hasattr(user_valves, "model_dump"):
                return Pipe.UserValves(**user_valves.model_dump())
            return Pipe.UserValves(**user_valves.dict())
        return Pipe.UserValves(**(user_valves or {}))

    @staticmethod
    def _get_user(user_data: Any) -> UserModel:
        if isinstance(user_data, UserModel):
            return user_data
        if isinstance(user_data, BaseModel):
            if hasattr(user_data, "model_dump"):
                user_data = user_data.model_dump()
            else:
                user_data = user_data.dict()
        if isinstance(user_data, dict):
            return UserModel(**{k: v for k, v in user_data.items() if k != "valves"})
        raise ValueError("user not found")

    @staticmethod
    def _format_data(
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
                    "delta" if is_stream else "message": {"content": content},
                }
            ]
        if usage:
            data["usage"] = usage
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
