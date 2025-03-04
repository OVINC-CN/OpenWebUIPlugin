from typing import List, Optional

import tiktoken
from apps.usage.models import AIModel
from django.conf import settings
from httpx import Client
from ovinc_client.core.logger import logger
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from tiktoken import Encoding


class ModelInfo(PydanticBaseModel):
    base_model_id: Optional[str] = None


class Model(PydanticBaseModel):
    id: str
    name: str
    info: ModelInfo = Field(default_factory=lambda: ModelInfo(base_model_id=None))


class ModelSyncer:
    """
    Sync Models from OpenWebUI
    """

    def sync(self) -> None:
        try:
            self._sync()
        except Exception as err:
            logger.exception("[sync_model] failed: %s", err)

    def _sync(self) -> None:
        with Client() as client:
            response = client.get(
                f"{settings.OPENWEBUI_URL.rstrip("/")}/api/models",
                headers={"Authorization": f"Bearer {settings.OPENWEBUI_KEY}"},
            )
            response.raise_for_status()
            models: list[Model] = [Model.model_validate(model) for model in response.json()["data"]]

        wait_list: list[Model] = []
        db_model_map: dict[str, AIModel] = {}
        for model in models:
            ai_model = AIModel.get_model(model.id)
            ai_model.model_name = model.name
            ai_model.save(update_fields=["model_name"])
            db_model_map[ai_model.model_id] = ai_model
            if model.info.base_model_id:
                wait_list.append(model)
        for model in wait_list:
            base_model = db_model_map.get(model.info.base_model_id)
            if not base_model:
                continue
            ai_model = db_model_map[model.id]
            ai_model.prompt_price = base_model.prompt_price
            ai_model.completion_price = base_model.completion_price
            ai_model.save(update_fields=["prompt_price", "completion_price"])


class UsageModel(PydanticBaseModel):
    model_config = ConfigDict(extra="allow")

    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)


class SourceSourceModel(PydanticBaseModel):
    model_config = ConfigDict(extra="allow")

    id: str


class SourceModel(PydanticBaseModel):
    model_config = ConfigDict(extra="allow")

    source: SourceSourceModel
    document: List[str]


class MessageItem(PydanticBaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    role: str
    content: str
    timestamp: int
    usage: Optional[UsageModel] = None
    sources: Optional[List[SourceModel]] = None


class MessageBody(PydanticBaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: List[MessageItem]


class Calculator:
    """
    Usage Calculator
    """

    def __init__(self) -> None:
        self._encoder = {}
        if settings.IGNORE_MODEL_ENCODING:
            self.get_encoder(settings.DEFAULT_MODEL_FOR_TOKEN)

    def get_encoder(self, model_id: str) -> Encoding:
        if settings.IGNORE_MODEL_ENCODING:
            model_id = settings.DEFAULT_MODEL_FOR_TOKEN
        # remove prefix
        model_id_ops = model_id
        if settings.MODEL_PREFIX_TO_REMOVE:
            model_id_ops = model_id.lstrip(settings.MODEL_PREFIX_TO_REMOVE)
        # load from cache
        if model_id_ops in self._encoder:
            return self._encoder[model_id_ops]
        # load from tiktoken
        try:
            self._encoder[model_id_ops] = tiktoken.encoding_for_model(model_id_ops)
        except KeyError:
            return self.get_encoder(settings.DEFAULT_MODEL_FOR_TOKEN)
        return self.get_encoder(model_id)

    def calculate_usage(self, body: dict) -> UsageModel:
        try:
            # init
            body = MessageBody.model_validate(body)
            # usage
            if body.messages[-1].usage is not None:
                return body.messages[-1].usage
            logger.warning("no usage info, calculating %s", body.model)
            # calculate
            encoder = self.get_encoder(body.model)
            usage = UsageModel()
            # prompt tokens
            source_ids = set()
            for index, message in enumerate(body.messages):
                if index < len(body.messages) - 1:
                    usage.prompt_tokens += len(encoder.encode(message.content))
                if message.sources:
                    for source in message.sources:
                        if source.source.id in source_ids:
                            continue
                        source_ids.add(source.source.id)
                        for doc in source.document:
                            usage.prompt_tokens += len(encoder.encode(doc))
            # completion tokens
            usage.completion_tokens = len(encoder.encode(body.messages[-1].content))
            # total tokens
            usage.total_tokens = usage.prompt_tokens + usage.completion_tokens
            return usage
        except Exception as err:
            logger.exception("[calculate_usage] failed: %s", err)
            raise err


calculator = Calculator()
