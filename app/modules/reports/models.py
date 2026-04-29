from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from app.core.odm import Document, PydanticObjectId
from app.core.utils import utcnow


class ReportType(str, Enum):
    test = "test"
    user = "user"
    group = "group"
    date = "date"
    private_link = "private_link"
    errors = "errors"
    user_result = "user_result"
    group_result = "group_result"
    test_result = "test_result"


class ReportFilters(dict):
    pass


class ReportOptions(dict):
    pass


class ReportRecord(Document):
    report_number: str = ""
    type: ReportType
    title: str = ""
    filters: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, bool] = Field(default_factory=dict)
    test_id: PydanticObjectId | None = None
    user_id: PydanticObjectId | None = None
    group_id: PydanticObjectId | None = None
    private_link_id: PydanticObjectId | None = None
    generated_by: PydanticObjectId
    file_path: str
    updated_at: datetime = Field(default_factory=utcnow)
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "reports"
        indexes = [
            "report_number",
            "generated_by",
            "test_id",
            "user_id",
            "group_id",
            "private_link_id",
            "created_at",
            "type",
        ]
