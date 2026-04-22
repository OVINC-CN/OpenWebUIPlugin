"""
title: OpenAI Image
author: OVINC CN, yuzukumo
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.1.1
licence: MIT
"""

import base64
import json
import logging
import mimetypes
import re
import time
import uuid
from typing import Any, AsyncIterable, List, Literal, Optional, Tuple

import httpx
from fastapi import Request
from httpx import Response
from open_webui.env import GLOBAL_LOG_LEVEL
from open_webui.models.users import UserModel
from open_webui.routers.files import get_file_content_by_id
from open_webui.routers.images import get_image_data, upload_image
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
            return json.loads(self._content)["error"]["message"]
        except Exception:
            pass
        try:
            self._response.raise_for_status()
        except Exception as err:
            return str(err)
        return "Unknown API error"


class Pipe:
    class Valves(BaseModel):
        base_url: str = Field(default="https://api.openai.com/v1", title="Base URL")
        api_key: str = Field(default="", title="API Key")
        num_of_images: int = Field(default=1, title="图片数量", ge=1, le=10)
        timeout: int = Field(default=600, title="请求超时（秒）")
        proxy: str = Field(default="", title="代理地址")
        models: str = Field(
            default="gpt-image-2",
            title="支持模型列表",
            description="多个模型用逗号分隔",
        )

    class UserValves(BaseModel):
        quality: Literal["low", "medium", "high", "auto"] = Field(default="auto", title="图片质量")
        size_preset: Literal[
            "auto",
            "1024x1024",
            "1536x1024",
            "1024x1536",
            "2048x2048",
            "2048x1152",
            "3840x2160",
            "2160x3840",
            "customize",
        ] = Field(
            default="auto",
            title="图片分辨率",
        )
        custom_size: str = Field(
            default="1024x1024",
            title="自定义分辨率",
            description="仅在分辨率选择 customize 时生效，例如 1024x1024",
        )
        moderation: Literal["auto", "low"] = Field(default="auto", title="审核级别")
        output_format: Literal["png", "jpeg", "webp"] = Field(default="png", title="输出格式")
        output_compression: int = Field(default=100, title="压缩质量", ge=0, le=100)
        enable_mask_mode: bool = Field(default=False, title="启用 Mask 模式")

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
            self._pipe(body=body, __user__=__user__, __request__=__request__, __metadata__=__metadata__)
        )

    async def _pipe(
        self,
        body: dict,
        __user__: dict,
        __request__: Request,
        __metadata__: Optional[dict] = None,
    ) -> AsyncIterable[str]:
        user = self._get_user(__user__)

        model, payload, output_format = await self._build_payload(
            user=user, body=body, user_valves=__user__.get("valves", {})
        )
        is_stream = bool(body.get("stream"))

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
            response_json = response.json()

            content = await self._parse_response_images(
                response_json=response_json,
                output_format=output_format,
                user=user,
                __request__=__request__,
                metadata=__metadata__,
            )
            usage = self._extract_usage(response_json)
            if is_stream:
                yield self._format_data(is_stream=True, model=model, content=content, usage=None)
                if usage:
                    yield self._format_data(is_stream=True, model=model, content=None, usage=usage)
                return

            yield self._format_data(is_stream=False, model=model, content=content, usage=usage)

    async def _build_payload(self, user: UserModel, body: dict, user_valves: Any) -> Tuple[str, dict, str]:
        user_valves = self._normalize_user_valves(user_valves)
        model = body["model"].split(".", 1)[1] if "." in body["model"] else body["model"]

        prompt, images = await self._parse_messages(user=user, body=body)
        mask = await self._parse_mask(user=user, body=body)
        size = self._resolve_size(user_valves=user_valves)

        data = {
            "model": model,
            "prompt": prompt,
        }

        if user_valves.quality != "auto":
            data["quality"] = user_valves.quality
        if size:
            data["size"] = size
        if user_valves.moderation != "auto":
            data["moderation"] = user_valves.moderation
        if user_valves.output_format != "png":
            data["output_format"] = user_valves.output_format
        if user_valves.output_format in {"jpeg", "webp"} and user_valves.output_compression != 100:
            data["output_compression"] = user_valves.output_compression

        if not images:
            data["n"] = self.valves.num_of_images
            payload = {"url": "/images/generations", "json": data}
            return model, payload, user_valves.output_format

        if len(images) > 16:
            raise ValueError("OpenAI image edits support up to 16 input images.")

        if user_valves.enable_mask_mode and len(images) >= 2 and not mask:
            mask = images[1]
            images = [images[0], *images[2:]]

        edit_data = dict(data)
        if self.valves.num_of_images > 1:
            edit_data["n"] = self.valves.num_of_images

        files = [
            await self._image_ref_to_multipart_file(user=user, image_ref=image, field_name="image[]")
            for image in images
        ]
        if mask:
            files.append(await self._image_ref_to_multipart_file(user=user, image_ref=mask, field_name="mask"))

        payload = {
            "url": "/images/edits",
            "data": self._stringify_form_data(edit_data),
            "files": files,
        }
        return model, payload, user_valves.output_format

    async def _parse_messages(self, user: UserModel, body: dict) -> Tuple[str, List[dict]]:
        prompt_parts: List[str] = []
        images: List[dict] = []

        messages = body.get("messages", [])
        if len(messages) >= 4:
            messages = messages[-4:]

        for message in messages:
            if message.get("role") == "system":
                continue

            allow_text = message.get("role") != "assistant"
            message_content = message.get("content")

            if isinstance(message_content, str):
                for item in message_content.split("\n"):
                    item = item.strip()
                    if not item:
                        continue
                    if item.startswith("![openai-image-"):
                        images.append(await self._markdown_to_image_ref(user, item))
                        continue
                    if allow_text:
                        prompt_parts.append(item)
                continue

            if isinstance(message_content, list):
                for content in message_content:
                    if content["type"] == "text":
                        text = content.get("text", "").strip()
                        if text and allow_text:
                            prompt_parts.append(text)
                        continue
                    if content["type"] in {"image_url", "input_image"}:
                        images.append(self._image_ref_from_content(content))
                        continue
                    raise TypeError("message content invalid")
                continue

            raise TypeError("message content invalid")

        prompt = "\n".join(prompt_parts).strip()
        if not prompt:
            prompt = body.get("prompt", "Please generate an image.")
        return prompt, images

    async def _parse_mask(self, user: UserModel, body: dict) -> Optional[dict]:
        mask = body.get("mask")
        if not mask:
            return None
        return await self._normalize_image_ref(user, mask)

    async def _parse_response_images(
        self,
        response_json: dict,
        output_format: str,
        user: UserModel,
        __request__: Request,
        metadata: Optional[dict],
    ) -> str:
        results = []
        for item in self._collect_image_items(response_json):
            rendered = await self._render_documented_image_item(
                item=item,
                output_format=output_format,
                user=user,
                __request__=__request__,
                metadata=metadata,
            )
            if rendered:
                results.append(rendered)

        if not results and response_json.get("error"):
            raise ValueError(response_json["error"].get("message", "Unknown API error"))
        if not results:
            preview = json.dumps(response_json, ensure_ascii=False)
            if len(preview) > 600:
                preview = f"{preview[:600]}..."
            raise ValueError(f"No image returned by OpenAI image API. Response preview: {preview}")

        return "\n\n".join(results)

    async def _render_documented_image_item(
        self,
        item: dict,
        output_format: str,
        user: UserModel,
        __request__: Request,
        metadata: Optional[dict],
    ) -> str:
        if not isinstance(item, dict):
            return ""
        image_data = item.get("b64_json")
        if image_data:
            mime_type = item.get("mime_type") or self._mime_type_for_format(output_format)
            return await self._upload_image(
                __request__=__request__,
                user=user,
                image_source=image_data,
                mime_type=mime_type,
                metadata=metadata,
            )
        image_url = item.get("url")
        if image_url:
            return await self._upload_image(
                __request__=__request__,
                user=user,
                image_source=image_url,
                mime_type=self._mime_type_for_format(output_format),
                metadata=metadata,
            )
        return ""

    async def _upload_image(
        self,
        __request__: Request,
        user: UserModel,
        image_source: str,
        mime_type: str,
        metadata: Optional[dict],
    ) -> str:
        headers = None
        if image_source.startswith("http://") or image_source.startswith("https://"):
            headers = {"Authorization": f"Bearer {self.valves.api_key}"}

        image_bytes, detected_mime_type = await get_image_data(image_source, headers=headers)
        if image_bytes is None:
            raise ValueError("invalid image data returned by OpenAI image API")

        file_item, image_url = await upload_image(
            request=__request__,
            image_data=image_bytes,
            content_type=detected_mime_type or mime_type,
            metadata={"mime_type": detected_mime_type or mime_type, **(metadata or {})},
            user=user,
        )
        return f"![openai-image-{file_item.id}]({image_url})"

    async def _markdown_to_image_ref(self, user: UserModel, markdown_string: str) -> dict:
        file_id = markdown_string.split("![openai-image-")[1].split("]")[0]
        return await self._normalize_image_ref(user, file_id)

    async def _normalize_image_ref(self, user: UserModel, value: Any) -> dict:
        if isinstance(value, dict):
            if "image_url" in value or "file_id" in value:
                return value
            raise TypeError("invalid image reference")

        if not isinstance(value, str):
            raise TypeError("invalid image reference")

        if value.startswith("![openai-image-"):
            file_id = value.split("![openai-image-")[1].split("]")[0]
            return await self._normalize_image_ref(user, file_id)

        if value.startswith("http://") or value.startswith("https://") or value.startswith("data:"):
            return {"image_url": value}

        file_response = await get_file_content_by_id(id=value, user=user)
        mime_type = mimetypes.guess_type(file_response.path)[0] or "image/png"
        with open(file_response.path, "rb") as file_content:
            encoded = base64.b64encode(file_content.read()).decode()
        return {"image_url": f"data:{mime_type};base64,{encoded}"}

    @staticmethod
    def _image_ref_from_content(content: dict) -> dict:
        image_url = content["image_url"]["url"]
        return {"image_url": image_url}

    async def _image_ref_to_multipart_file(
        self,
        user: UserModel,
        image_ref: dict,
        field_name: str,
    ) -> tuple[str, tuple[str, bytes, str]]:
        image_bytes, mime_type = await self._image_ref_to_bytes(user=user, image_ref=image_ref)
        file_ext = mimetypes.guess_extension(mime_type) or ".png"
        if file_ext == ".jpe":
            file_ext = ".jpg"
        return (
            field_name,
            (f"{uuid.uuid4().hex}{file_ext}", image_bytes, mime_type),
        )

    async def _image_ref_to_bytes(self, user: UserModel, image_ref: dict) -> tuple[bytes, str]:
        if not isinstance(image_ref, dict):
            raise TypeError("invalid image reference")

        if "file_id" in image_ref:
            file_response = await get_file_content_by_id(id=image_ref["file_id"], user=user)
            with open(file_response.path, "rb") as file_content:
                image_bytes = file_content.read()
            mime_type = file_response.media_type or mimetypes.guess_type(file_response.path)[0] or "image/png"
            return image_bytes, mime_type

        image_url = image_ref.get("image_url")
        if isinstance(image_url, dict):
            image_url = image_url.get("url", "")
        if not isinstance(image_url, str) or not image_url:
            raise TypeError("invalid image reference")

        image_bytes, mime_type = await get_image_data(image_url)
        if image_bytes is None or not mime_type:
            raise ValueError("invalid image input")
        return image_bytes, mime_type

    @staticmethod
    def _stringify_form_data(data: dict) -> dict:
        form_data = {}
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, bool):
                form_data[key] = "true" if value else "false"
            else:
                form_data[key] = str(value)
        return form_data

    @staticmethod
    def _collect_image_items(payload: Any) -> list[dict]:
        if not isinstance(payload, dict):
            return []

        items = []
        for container in (payload, payload.get("response")):
            if not isinstance(container, dict):
                continue

            data = container.get("data")
            if isinstance(data, list):
                items.extend(item for item in data if isinstance(item, dict))
            elif isinstance(data, dict):
                items.append(data)

            if any(key in container for key in ("b64_json", "url")):
                items.append(container)

        return items

    @staticmethod
    def _extract_usage(payload: Any) -> Optional[dict]:
        if not isinstance(payload, dict):
            return None

        usage = payload.get("usage")
        if isinstance(usage, dict):
            return usage

        response = payload.get("response")
        if isinstance(response, dict):
            usage = response.get("usage")
            if isinstance(usage, dict):
                return usage

        return None

    @staticmethod
    def _mime_type_for_format(output_format: str) -> str:
        return {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
        }.get(output_format, "image/png")

    @staticmethod
    def _resolve_size(user_valves: "Pipe.UserValves") -> Optional[str]:
        if user_valves.size_preset == "auto":
            return None

        if user_valves.size_preset == "customize":
            size = user_valves.custom_size.strip()
        else:
            size = user_valves.size_preset

        width, height = Pipe._parse_size_string(size)
        normalized_size = f"{width}x{height}"
        Pipe._validate_gpt_image_2_size(normalized_size)
        return normalized_size

    @staticmethod
    def _validate_gpt_image_2_size(size: str) -> None:
        width, height = Pipe._parse_size_string(size)
        pixels = width * height
        short_edge = min(width, height)
        long_edge = max(width, height)

        if width > 3840 or height > 3840:
            raise ValueError("gpt-image-2 widths and heights must be 3840 pixels or smaller.")
        if width % 16 != 0 or height % 16 != 0:
            raise ValueError("gpt-image-2 widths and heights must be multiples of 16.")
        if pixels < 655360 or pixels > 8294400:
            raise ValueError("gpt-image-2 image sizes must stay between 655,360 and 8,294,400 total pixels.")
        if long_edge > short_edge * 3:
            raise ValueError("gpt-image-2 aspect ratio cannot exceed 3:1.")

    @staticmethod
    def _parse_size_string(size: str) -> tuple[int, int]:
        normalized = size.strip().lower()
        match = re.fullmatch(r"(\d+)\s*x\s*(\d+)", normalized)
        if not match:
            raise ValueError("Custom size must use WIDTHxHEIGHT format, for example 2048x1152.")
        return int(match.group(1)), int(match.group(2))

    @staticmethod
    def _normalize_user_valves(user_valves: Any) -> "Pipe.UserValves":
        if isinstance(user_valves, Pipe.UserValves):
            return user_valves
        if isinstance(user_valves, BaseModel):
            if hasattr(user_valves, "model_dump"):
                user_valves = user_valves.model_dump()
            else:
                user_valves = user_valves.dict()
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
                    "delta" if is_stream else "message": {
                        "content": content,
                    },
                }
            ]
        if usage:
            data["usage"] = usage
        return f"data: {json.dumps(data)}\n\n"
