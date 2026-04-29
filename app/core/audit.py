from app.modules.users.models import AuditLog


async def log_action(
    user_id: str | None,
    action: str,
    object_type: str,
    object_id: str | None = None,
    meta: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        meta=meta or {},
    )
    await entry.insert()
    return entry
