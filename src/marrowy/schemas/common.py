from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EventPayload(ORMModel):
    id: str
    event_type: str
    payload_json: dict[str, Any]
    created_at: datetime
