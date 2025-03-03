from typing import Optional

from apps.usage.models import AIModel
from django.conf import settings
from httpx import Client
from ovinc_client.core.logger import logger
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field


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
