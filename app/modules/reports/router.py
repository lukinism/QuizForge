from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse

from app.core.audit import log_action
from app.core.config import get_settings
from app.core.dependencies import require_roles
from app.core.templates import templates
from app.modules.groups.service import list_groups
from app.modules.reports.models import ReportType
from app.modules.reports.permissions import can_download_report, can_view_report
from app.modules.reports.schemas import REPORT_STATUS_CHOICES, ReportCreateInput, ReportFiltersInput, ReportOptionsInput
from app.modules.reports.service import (
    generate_report,
    get_report_by_number,
    get_report_or_404,
    list_reports,
)
from app.modules.tests.models import TestLink
from app.modules.tests.service import list_manageable_tests
from app.modules.users.models import User, UserRole
from app.modules.users.service import list_users


router = APIRouter(prefix="/reports", tags=["reports"])


async def _create_form_context(request: Request, current_user: User, error: str | None = None) -> dict:
    tests = await list_manageable_tests(current_user)
    test_ids = [test.id for test in tests]
    links = await TestLink.find({"test_id": {"$in": test_ids}}).sort("-created_at").to_list() if test_ids else []
    return {
        "current_user": current_user,
        "report_types": [ReportType.test, ReportType.user, ReportType.group, ReportType.date, ReportType.private_link, ReportType.errors],
        "status_choices": REPORT_STATUS_CHOICES,
        "tests": tests,
        "groups": await list_groups(current_user),
        "users": await list_users(),
        "links": links,
        "error": error or request.query_params.get("toast"),
    }


@router.get("")
async def reports_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    users = await list_users()
    user_map = {user.id: user for user in users}
    return templates.TemplateResponse(
        request=request,
        name="reports/index.html",
        context={"current_user": current_user, "reports": await list_reports(current_user), "user_map": user_map},
    )


@router.get("/create")
async def create_report_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    return templates.TemplateResponse(
        request=request,
        name="reports/create.html",
        context=await _create_form_context(request, current_user),
    )


@router.post("/create")
async def create_report_submit(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    report_type: ReportType = Form(...),
    test_id: str = Form(""),
    group_id: str = Form(""),
    user_id: str = Form(""),
    private_link_id: str = Form(""),
    date_from: str = Form(""),
    date_to: str = Form(""),
    status_filter: str = Form(""),
    include_answers: bool = Form(False),
    include_correct_answers: bool = Form(False),
    include_statistics: bool = Form(False),
    include_charts: bool = Form(False),
    include_signature: bool = Form(False),
    include_qr: bool = Form(False),
):
    try:
        payload = ReportCreateInput(
            report_type=report_type,
            filters=ReportFiltersInput(
                test_id=test_id or None,
                group_id=group_id or None,
                user_id=user_id or None,
                private_link_id=private_link_id or None,
                date_from=date_from or None,
                date_to=date_to or None,
                status=status_filter or None,
            ),
            options=ReportOptionsInput(
                include_answers=include_answers,
                include_correct_answers=include_correct_answers,
                include_statistics=include_statistics,
                include_charts=include_charts,
                include_signature=include_signature,
                include_qr=include_qr,
            ),
        )
        report = await generate_report(payload, current_user, request)
    except HTTPException as exc:
        return templates.TemplateResponse(
            request=request,
            name="reports/create.html",
            context=await _create_form_context(request, current_user, str(exc.detail)),
            status_code=exc.status_code,
        )
    return RedirectResponse(url=f"/reports/{report.id}?created=1", status_code=303)


@router.get("/verify/{report_number}")
async def verify_report_page(report_number: str, request: Request):
    report = await get_report_by_number(report_number)
    generated_by = await User.get(report.generated_by) if report else None
    return templates.TemplateResponse(
        request=request,
        name="reports/verify.html",
        context={
            "current_user": None,
            "report": report,
            "generated_by": generated_by,
            "is_valid": report is not None,
        },
        status_code=200 if report else 404,
    )


@router.get("/{report_id}")
async def report_detail_page(
    report_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    report = await get_report_or_404(report_id)
    await can_view_report(current_user, report)
    generated_by = await User.get(report.generated_by)
    return templates.TemplateResponse(
        request=request,
        name="reports/detail.html",
        context={"current_user": current_user, "report": report, "generated_by": generated_by},
    )


@router.get("/{report_id}/download")
async def download_report(
    report_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    report = await get_report_or_404(report_id)
    await can_download_report(current_user, report)

    settings = get_settings()
    storage_root = Path(settings.report_storage_dir).resolve()
    report_path = Path(report.file_path).resolve()
    if storage_root not in report_path.parents or not report_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл PDF не найден.")

    await log_action(str(current_user.id), "download_report", "report", str(report.id), {"report_number": report.report_number})
    return FileResponse(report_path, media_type="application/pdf", filename=report_path.name)


@router.post("/user/{attempt_id}")
async def create_user_report_legacy(
    attempt_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    from app.modules.attempts.models import Attempt
    from app.core.utils import parse_object_id

    attempt = await Attempt.get(parse_object_id(attempt_id))
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Попытка не найдена.")
    payload = ReportCreateInput(
        report_type=ReportType.user,
        filters=ReportFiltersInput(user_id=attempt.user_id, test_id=attempt.test_id),
        options=ReportOptionsInput(include_answers=True, include_correct_answers=True, include_statistics=True, include_qr=True),
    )
    report = await generate_report(payload, current_user, request)
    return RedirectResponse(url=f"/reports/{report.id}/download", status_code=303)


@router.post("/group/{group_id}")
async def create_group_report_legacy(
    group_id: str,
    request: Request,
    test_id: str = Form(...),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    payload = ReportCreateInput(
        report_type=ReportType.group,
        filters=ReportFiltersInput(group_id=group_id, test_id=test_id),
        options=ReportOptionsInput(include_statistics=True, include_qr=True),
    )
    report = await generate_report(payload, current_user, request)
    return RedirectResponse(url=f"/reports/{report.id}/download", status_code=303)


@router.post("/test/{test_id}")
async def create_test_report_legacy(
    test_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    payload = ReportCreateInput(
        report_type=ReportType.test,
        filters=ReportFiltersInput(test_id=test_id),
        options=ReportOptionsInput(include_statistics=True, include_charts=True, include_qr=True),
    )
    report = await generate_report(payload, current_user, request)
    return RedirectResponse(url=f"/reports/{report.id}/download", status_code=303)
