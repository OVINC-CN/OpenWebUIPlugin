"""
title: Gemini Image
description: Image generation with Gemini
author: OVINC CN, yuzukumo
git_url: https://github.com/OVINC-CN/OpenWebUIPlugin.git
version: 0.1.0
licence: MIT
"""

import base64
import json
import logging
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
            default="https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            title="Base URL",
        )
        api_key: str = Field(default="", title="API Key")
        timeout: int = Field(default=600, title="请求超时时间 (秒)")
        proxy: Optional[str] = Field(default="", title="代理地址")
        models: str = Field(
            default="gemini-3.1-flash-image-preview,gemini-3-pro-image-preview",
            title="模型",
            description="使用英文逗号分隔多个模型",
        )
        response_modalities: Literal["TEXT", "IMAGE", "TEXT,IMAGE"] = Field(
            default="IMAGE", title="响应模态", description="使用英文逗号分隔"
        )

    class UserValves(BaseModel):
        image_size: Literal["512", "1K", "2K", "4K"] = Field(default="1K", title="图片大小 (像素)")
        aspect_ratio: Literal[
            "1:1",
            "1:4",
            "1:8",
            "2:3",
            "3:2",
            "3:4",
            "4:1",
            "4:3",
            "4:5",
            "5:4",
            "8:1",
            "9:16",
            "16:9",
            "21:9",
        ] = Field(default="1:1", title="图片比例")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self):
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
            headers={"x-goog-api-key": self.valves.api_key},
            proxy=self.valves.proxy or None,
            trust_env=True,
            timeout=self.valves.timeout,
        ) as client:
            response = await client.post(**payload)
            if response.status_code != 200:
                raise APIException(status=response.status_code, content=response.text, response=response)
            response_json = response.json()

            results = []
            for item in response_json.get("candidates", []):
                content = item.get("content", {})
                if not content:
                    results.append(item.get("finishReason", ""))
                    continue
                parts = content.get("parts", [])
                if not parts:
                    results.append(item.get("finishReason", ""))
                    continue
                for part in parts:
                    if "text" in part:
                        results.append(part["text"])
                    if "inlineData" in part:
                        inline_data = part["inlineData"]
                        results.append(
                            await self._upload_image(
                                __request__=__request__,
                                user=user,
                                image_data=inline_data["data"],
                                mime_type=inline_data["mimeType"],
                                metadata=__metadata__,
                            )
                        )

            usage_metadata = dict(response_json.get("usageMetadata") or {})
            usage = {
                "prompt_tokens": usage_metadata.pop("promptTokenCount", 0),
                "completion_tokens": usage_metadata.pop("candidatesTokenCount", 0),
                "total_tokens": usage_metadata.pop("totalTokenCount", 0),
                "prompt_tokens_details": {"cached_tokens": usage_metadata.get("cachedContentTokenCount", 0)},
                "metadata": usage_metadata,
            }
            if usage_metadata and "toolUsePromptTokenCount" in usage_metadata:
                usage["prompt_tokens"] += usage_metadata["toolUsePromptTokenCount"]
            if usage_metadata and "thoughtsTokenCount" in usage_metadata:
                usage["completion_tokens"] += usage_metadata["thoughtsTokenCount"]
            if usage["prompt_tokens"] + usage["completion_tokens"] != usage["total_tokens"]:
                usage["completion_tokens"] = usage["total_tokens"] - usage["prompt_tokens"]

            # response
            content = "\n\n".join(results)
            if body.get("stream"):
                yield self._format_data(is_stream=True, model=model, content=content, usage=None)
                yield self._format_data(is_stream=True, model=model, content=None, usage=usage)
            else:
                yield self._format_data(is_stream=False, model=model, content=content, usage=usage)

    async def _upload_image(
        self,
        __request__: Request,
        user: UserModel,
        image_data: str,
        mime_type: str,
        metadata: Optional[dict],
    ) -> str:
        file_item, image_url = await upload_image(
            request=__request__,
            image_data=base64.b64decode(image_data),
            content_type=mime_type,
            metadata={"mime_type": mime_type, **(metadata or {})},
            user=user,
        )
        return f"![gemini-image-{file_item.id}]({image_url})"

    async def _markdown_to_inline_image_part(self, user: UserModel, markdown_string: str) -> dict:
        file_id = self._extract_file_id_from_markdown(markdown_string)
        if not file_id:
            raise ValueError("invalid image markdown")

        file_response = await get_file_content_by_id(id=file_id, user=user)
        with open(file_response.path, "rb") as file_content:
            image_bytes = file_content.read()

        mime_type = file_response.media_type or "image/png"
        return {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode(),
            }
        }

    async def _build_payload(self, user: UserModel, body: dict, user_valves: Any) -> Tuple[str, dict]:
        model = body["model"].split(".", 1)[1] if "." in body["model"] else body["model"]
        user_valves = self._normalize_user_valves(user_valves)
        self._validate_model_options(model=model, user_valves=user_valves)
        parts: List[dict] = []
        has_text = False
        image_count = 0

        messages = body.get("messages", [])
        if len(messages) > 6:
            messages = messages[-6:]
        for message in messages:
            role = message.get("role")
            if role == "system":
                continue

            allow_text = role != "assistant"
            message_content = message.get("content")
            if isinstance(message_content, str):
                for item in message_content.split("\n"):
                    item = item.strip()
                    if not item:
                        continue
                    if item.startswith("![") and "-image-" in item:
                        parts.append(await self._markdown_to_inline_image_part(user, item))
                        image_count += 1
                        continue
                    if allow_text:
                        parts.append({"text": item})
                        has_text = True
                continue

            if isinstance(message_content, list):
                for content in message_content:
                    content_type = content.get("type")
                    if content_type == "text":
                        text = content.get("text", "").strip()
                        if text and allow_text:
                            parts.append({"text": text})
                            has_text = True
                        continue
                    if content_type in {"image_url", "input_image"}:
                        parts.append(await self._content_to_inline_image_part(content))
                        image_count += 1
                        continue
                    raise TypeError("message content invalid")
                continue

            raise TypeError("message content invalid")

        if image_count > 14:
            raise ValueError("Gemini 3 image models support up to 14 reference images.")

        if not has_text:
            prompt = body.get("prompt", "Please generate an image.").strip()
            if prompt:
                parts.append({"text": prompt})

        payload = {
            "url": self.valves.base_url.format(model=model),
            "json": {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "responseModalities": self.valves.response_modalities.split(","),
                    "imageConfig": {
                        "aspectRatio": user_valves.aspect_ratio,
                        "imageSize": user_valves.image_size,
                    },
                },
            },
        }

        if body.get("tools", []):
            payload["json"]["tools"] = body["tools"]

        return model, payload

    async def _content_to_inline_image_part(self, content: dict) -> dict:
        image_url = self._extract_image_url(content)
        if not image_url:
            raise TypeError("message content invalid")

        image_bytes, mime_type = await get_image_data(image_url)
        if image_bytes is None or not mime_type:
            raise ValueError("invalid image input")

        return {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode(),
            }
        }

    @staticmethod
    def _extract_image_url(content: dict) -> str:
        image_url = content.get("image_url", "")
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
    def _normalize_user_valves(user_valves: Any) -> "Pipe.UserValves":
        if isinstance(user_valves, Pipe.UserValves):
            return user_valves
        if isinstance(user_valves, BaseModel):
            if hasattr(user_valves, "model_dump"):
                return Pipe.UserValves(**user_valves.model_dump())
            return Pipe.UserValves(**user_valves.dict())
        return Pipe.UserValves(**(user_valves or {}))

    @staticmethod
    def _validate_model_options(model: str, user_valves: "Pipe.UserValves") -> None:
        flash_only_aspect_ratios = {"1:4", "1:8", "4:1", "8:1"}
        if model == "gemini-3-pro-image-preview":
            if user_valves.image_size == "512":
                raise ValueError("Gemini 3 Pro Image Preview does not support 512 resolution.")
            if user_valves.aspect_ratio in flash_only_aspect_ratios:
                raise ValueError("Gemini 3 Pro Image Preview does not support 1:4, 1:8, 4:1, or 8:1 aspect ratios.")

    @staticmethod
    def _get_user(user_data: UserModel | BaseModel | dict) -> UserModel:
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
