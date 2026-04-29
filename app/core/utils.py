from datetime import datetime, timezone
from pathlib import Path

from bson import ObjectId
from fastapi import HTTPException, status

from app.core.odm import PydanticObjectId


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_object_id(value: str) -> PydanticObjectId:
    if isinstance(value, str) and ObjectId.is_valid(value):
        return value
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Запрошенный объект не найден.",
    )


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_duration(started_at: datetime, finished_at: datetime | None) -> str:
    start = ensure_utc_aware(started_at)
    end = ensure_utc_aware(finished_at) or utcnow()
    delta = end - start
    total_seconds = max(int(delta.total_seconds()), 0)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
