from fastapi import HTTPException, status

from app.core.audit import log_action
from app.core.utils import parse_object_id
from app.modules.groups.models import Group
from app.modules.reports.models import ReportRecord, ReportType
from app.modules.tests.models import Test, TestLink
from app.modules.users.models import User, UserRole


async def _ensure_examiner_owns_test(current_user: User, test_id: str | None) -> None:
    if current_user.role == UserRole.admin or not test_id:
        return
    test = await Test.get(parse_object_id(test_id))
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тест не найден.")
    if test.author_id != current_user.id:
        await log_action(
            str(current_user.id),
            "report_foreign_access_attempt",
            "test",
            test_id,
            {"reason": "examiner tried to generate report for foreign test"},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")


async def _ensure_examiner_owns_group(current_user: User, group_id: str | None) -> None:
    if current_user.role == UserRole.admin or not group_id:
        return
    group = await Group.get(parse_object_id(group_id))
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена.")
    if group.created_by != current_user.id:
        await log_action(str(current_user.id), "report_foreign_access_attempt", "group", group_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")


async def _ensure_examiner_owns_private_link(current_user: User, private_link_id: str | None) -> None:
    if current_user.role == UserRole.admin or not private_link_id:
        return
    link = await TestLink.get(parse_object_id(private_link_id))
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Приватная ссылка не найдена.")
    await _ensure_examiner_owns_test(current_user, link.test_id)


async def can_generate_report(current_user: User, report_type: ReportType, filters: dict) -> bool:
    if current_user.role not in {UserRole.admin, UserRole.examiner}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    test_id = filters.get("test_id")
    group_id = filters.get("group_id")
    private_link_id = filters.get("private_link_id")

    required = {
        ReportType.test: ("test_id", "Для отчета по тесту выберите тест."),
        ReportType.user: ("user_id", "Для отчета по пользователю выберите пользователя."),
        ReportType.group: ("group_id", "Для отчета по группе выберите группу."),
        ReportType.private_link: ("private_link_id", "Для отчета по приватной ссылке выберите ссылку."),
        ReportType.errors: ("test_id", "Для отчета по ошибкам выберите тест."),
    }
    if report_type in required:
        field, message = required[report_type]
        if not filters.get(field):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
    if report_type == ReportType.date and (not filters.get("date_from") or not filters.get("date_to")):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Для отчета по дате укажите период.")

    await _ensure_examiner_owns_test(current_user, test_id)
    await _ensure_examiner_owns_group(current_user, group_id)
    await _ensure_examiner_owns_private_link(current_user, private_link_id)
    return True


async def can_view_report(current_user: User, report: ReportRecord) -> bool:
    if current_user.role == UserRole.admin:
        return True
    if current_user.role == UserRole.examiner and report.generated_by == current_user.id:
        return True
    await log_action(str(current_user.id), "report_foreign_access_attempt", "report", str(report.id))
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")


async def can_download_report(current_user: User, report: ReportRecord) -> bool:
    return await can_view_report(current_user, report)
