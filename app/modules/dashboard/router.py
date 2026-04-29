from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from app.core.dependencies import get_current_user_optional, require_roles
from app.core.templates import templates
from app.modules.attempts.service import list_attempts_for_scope
from app.modules.dashboard.service import (
    get_admin_dashboard_stats,
    get_examiner_dashboard_stats,
    get_student_dashboard_stats,
)
from app.modules.tests.models import Test
from app.modules.tests.service import list_assignments_for_student
from app.modules.users.models import User, UserRole
from app.modules.users.service import list_users


router = APIRouter(tags=["dashboard"])


@router.get("/")
async def root_redirect(current_user: User | None = Depends(get_current_user_optional)):
    if not current_user:
        return RedirectResponse(url="/auth/login", status_code=303)
    if current_user.role == UserRole.admin:
        return RedirectResponse(url="/admin", status_code=303)
    if current_user.role == UserRole.examiner:
        return RedirectResponse(url="/examiner", status_code=303)
    return RedirectResponse(url="/student", status_code=303)


@router.get("/admin")
async def admin_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin)),
):
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "current_user": current_user,
            "stats": await get_admin_dashboard_stats(),
            "recent_users": (await list_users())[:5],
            "recent_tests": (await Test.find_all().sort("-updated_at").to_list())[:5],
            "recent_attempts": (await list_attempts_for_scope(current_user))[:5],
        },
    )


@router.get("/examiner")
async def examiner_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.examiner)),
):
    return templates.TemplateResponse(
        request=request,
        name="examiner/dashboard.html",
        context={
            "current_user": current_user,
            "stats": await get_examiner_dashboard_stats(current_user),
            "recent_tests": (await Test.find(Test.author_id == current_user.id).sort("-updated_at").to_list())[:5],
            "recent_attempts": (await list_attempts_for_scope(current_user))[:5],
        },
    )


@router.get("/student")
async def student_dashboard(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    assignments = await list_assignments_for_student(current_user)
    assigned_tests = await Test.find({"_id": {"$in": [assignment.test_id for assignment in assignments]}}).to_list() if assignments else []
    return templates.TemplateResponse(
        request=request,
        name="student/dashboard.html",
        context={
            "current_user": current_user,
            "stats": await get_student_dashboard_stats(current_user),
            "recent_attempts": (await list_attempts_for_scope(current_user))[:5],
            "assignments": assignments[:5],
            "assigned_tests_by_id": {test.id: test for test in assigned_tests},
        },
    )
