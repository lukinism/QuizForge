from enum import Enum
from typing import Any

from pydantic import EmailStr, Field

from app.core.odm import Document, Indexed
from app.core.utils import utcnow


class UserRole(str, Enum):
    admin = "admin"
    examiner = "examiner"
    student = "student"


class User(Document):
    email: Indexed(EmailStr, unique=True)
    username: Indexed(str, unique=True)
    full_name: str | None = None
    password_hash: str
    role: UserRole = UserRole.student
    is_active: bool = True
    created_at: Any = Field(default_factory=utcnow)
    updated_at: Any = Field(default_factory=utcnow)

    class Settings:
        name = "users"
        indexes = ["email", "username", "role"]


class AuditLog(Document):
    user_id: str | None = None
    action: str
    object_type: str
    object_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: Any = Field(default_factory=utcnow)

    class Settings:
        name = "audit_logs"
        indexes = ["user_id", "object_type", "object_id", "created_at"]
