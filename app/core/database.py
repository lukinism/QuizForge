from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ServerSelectionTimeoutError

from app.core.config import get_settings
from app.core.odm import init_odm, reset_odm
from app.modules.attempts.models import Attempt
from app.modules.groups.models import Group, GroupJoinEvent, GroupJoinLink
from app.modules.reports.models import ReportRecord
from app.modules.tests.models import Test, TestAssignment, TestLink
from app.modules.users.models import AuditLog, User


mongodb_client: AsyncIOMotorClient | None = None


async def init_db() -> None:
    global mongodb_client

    settings = get_settings()
    mongodb_client = AsyncIOMotorClient(settings.mongo_dsn, tz_aware=True)
    try:
        await init_odm(
            database=mongodb_client[settings.mongo_db],
            document_models=[
                User,
                AuditLog,
                Test,
                TestLink,
                TestAssignment,
                Attempt,
                Group,
                GroupJoinLink,
                GroupJoinEvent,
                ReportRecord,
            ],
        )
    except ServerSelectionTimeoutError as exc:
        raise RuntimeError(
            "MongoDB is unavailable. "
            f"Current MONGO_DSN={settings.mongo_dsn!r}. "
            "For local запуск use mongodb://127.0.0.1:27017, "
            "for Docker Compose use mongodb://mongodb:27017."
        ) from exc


async def close_db() -> None:
    global mongodb_client
    if mongodb_client is not None:
        mongodb_client.close()
        mongodb_client = None
    reset_odm()
