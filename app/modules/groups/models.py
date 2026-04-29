from datetime import datetime
from uuid import uuid4

from pydantic import Field

from app.core.odm import Document, PydanticObjectId
from app.core.utils import utcnow


class Group(Document):
    title: str
    description: str = ""
    created_by: PydanticObjectId
    members: list[PydanticObjectId] = Field(default_factory=list)
    blocked_members: list[PydanticObjectId] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "groups"
        indexes = ["created_by", "created_at", "title"]


class GroupJoinLink(Document):
    group_id: PydanticObjectId
    token: str = Field(default_factory=lambda: str(uuid4()))
    is_active: bool = True
    created_by: PydanticObjectId
    created_at: datetime = Field(default_factory=utcnow)
    revoked_at: datetime | None = None

    class Settings:
        name = "group_join_links"
        indexes = ["group_id", "token", "created_by", "is_active", "created_at"]


class GroupJoinEvent(Document):
    group_id: PydanticObjectId
    link_id: PydanticObjectId
    user_id: PydanticObjectId
    joined_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "group_join_events"
        indexes = ["group_id", "link_id", "user_id", "joined_at"]
