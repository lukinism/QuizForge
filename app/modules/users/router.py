from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.core.audit import log_action
from app.core.dependencies import require_roles
from app.core.templates import templates
from app.modules.attempts.models import Attempt, AttemptStatus
from app.modules.groups.models import Group
from app.modules.users.models import User, UserRole
from app.modules.users.service import (
    get_user_by_id,
    list_users,
    set_user_active_state,
    update_user_role,
)


router = APIRouter(prefix="/users", tags=["users"])


@router.get("/profile")
async def student_profile_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    attempts = await Attempt.find(Attempt.user_id == current_user.id).sort("-started_at").to_list()
    finished_attempts = [attempt for attempt in attempts if attempt.status == AttemptStatus.finished]
    groups = await Group.find({"members": current_user.id}).sort("-created_at").to_list()
    average_percent = round(
        sum(attempt.percent for attempt in finished_attempts) / len(finished_attempts),
        2,
    ) if finished_attempts else 0
    stats = {
        "attempts_count": len(attempts),
        "finished_count": len(finished_attempts),
        "passed_count": len([attempt for attempt in finished_attempts if attempt.is_passed]),
        "average_percent": average_percent,
        "groups_count": len(groups),
    }
    return templates.TemplateResponse(
        request=request,
        name="student/profile.html",
        context={
            "current_user": current_user,
            "stats": stats,
            "groups": groups,
            "recent_attempts": attempts[:8],
        },
    )


@router.get("")
async def users_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "current_user": current_user,
            "users": await list_users(),
            "roles": list(UserRole),
        },
    )


@router.post("/{user_id}/role")
async def update_role(
    user_id: str,
    role: UserRole = Form(...),
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    target_user = await get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден.")
    if target_user.id == current_user.id and role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Администратор не может снять с самого себя роль администратора.",
        )

    await update_user_role(target_user, role)
    await log_action(str(current_user.id), "update_role", "user", str(target_user.id), {"role": role.value})
    return RedirectResponse(url="/users", status_code=303)


@router.post("/{user_id}/toggle-active")
async def toggle_active(
    user_id: str,
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    target_user = await get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден.")
    if target_user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Администратор не может заблокировать самого себя.",
        )

    await set_user_active_state(target_user, not target_user.is_active)
    await log_action(
        str(current_user.id),
        "toggle_user_active",
        "user",
        str(target_user.id),
        {"is_active": target_user.is_active},
    )
    return RedirectResponse(url="/users", status_code=303)
