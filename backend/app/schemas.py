from datetime import datetime
import re
from typing import Any

from pydantic import BaseModel, Field


TAG_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_]{0,63}$")


def normalize_tag_name(value: str) -> str:
    name = (value or "").strip().lower()
    if not name:
        raise ValueError("标记名不能为空")
    if not TAG_NAME_PATTERN.match(name):
        raise ValueError("标记名仅允许小写字母、数字、- 与 _，且以字母或数字开头（≤64 字符）")
    return name


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class SampleOut(BaseModel):
    id: int
    name: str
    description: str
    is_broken: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class JobCreate(BaseModel):
    sampleId: int | None = None
    fastqText: str | None = Field(default=None, alias="fastqText")

    model_config = {"populate_by_name": True}


class StageOut(BaseModel):
    id: int
    actor_name: str
    stage_order: int
    status: str
    message: str | None
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class TagOut(BaseModel):
    id: int
    name: str
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    name: str

    def normalized_name(self) -> str:
        return normalize_tag_name(self.name)


class JobOut(BaseModel):
    id: int
    sample_id: int | None
    sample_name: str
    status: str
    created_by: str
    metrics: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
    stages: list[StageOut] = []
    tags: list[TagOut] = []

    model_config = {"from_attributes": True}


class JobListItem(BaseModel):
    id: int
    sample_id: int | None
    sample_name: str
    status: str
    created_by: str
    metrics: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
    tags: list[TagOut] = []

    model_config = {"from_attributes": True}


class HealthOut(BaseModel):
    status: str
    service: str
