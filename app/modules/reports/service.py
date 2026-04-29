from collections import Counter, defaultdict
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status

from app.core.audit import log_action
from app.core.config import get_settings
from app.core.utils import ensure_utc_aware, format_duration, parse_object_id, utcnow
from app.modules.attempts.models import Attempt, AttemptStatus
from app.modules.groups.models import Group
from app.modules.reports.charts import pass_fail_chart, question_error_chart, score_distribution
from app.modules.reports.models import ReportRecord, ReportType
from app.modules.reports.pdf import write_pdf
from app.modules.reports.permissions import can_generate_report
from app.modules.reports.qr import build_verify_url, make_qr_data_uri
from app.modules.reports.schemas import ReportCreateInput
from app.modules.tests.models import Test, TestLink
from app.modules.users.models import User, UserRole


REPORT_TITLES = {
    ReportType.test: "Отчет по тесту",
    ReportType.user: "Отчет по пользователю",
    ReportType.group: "Отчет по группе",
    ReportType.date: "Отчет по дате",
    ReportType.private_link: "Отчет по приватной ссылке",
    ReportType.errors: "Отчет по ошибкам",
}

REPORT_TEMPLATES = {
    ReportType.test: "test_report.html",
    ReportType.user: "user_report.html",
    ReportType.group: "group_report.html",
    ReportType.date: "date_report.html",
    ReportType.private_link: "private_link_report.html",
    ReportType.errors: "errors_report.html",
}


def _clean_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def _date_start(value) -> datetime | None:
    return datetime.combine(value, time.min, tzinfo=timezone.utc) if value else None


def _date_end(value) -> datetime | None:
    return datetime.combine(value, time.max, tzinfo=timezone.utc) if value else None


def _status_query(status_value: str | None) -> dict[str, Any]:
    if not status_value:
        return {}
    if status_value == "passed":
        return {"status": AttemptStatus.finished.value, "is_passed": True}
    if status_value == "failed":
        return {"status": AttemptStatus.finished.value, "is_passed": False}
    if status_value in {"pending_manual_review", "checked"}:
        return {"status": AttemptStatus.finished.value}
    if status_value in {item.value for item in AttemptStatus}:
        return {"status": status_value}
    return {}


def _attempt_query(filters: dict[str, Any]) -> dict[str, Any]:
    query: dict[str, Any] = {}
    for source, target in (
        ("test_id", "test_id"),
        ("user_id", "user_id"),
        ("private_link_id", "test_link_id"),
    ):
        if filters.get(source):
            query[target] = filters[source]
    if filters.get("date_from") or filters.get("date_to"):
        query["started_at"] = {}
        if filters.get("date_from"):
            query["started_at"]["$gte"] = _date_start(filters["date_from"])
        if filters.get("date_to"):
            query["started_at"]["$lte"] = _date_end(filters["date_to"])
    query.update(_status_query(filters.get("status")))
    return query


async def _group_member_ids(group_id: str | None) -> list[str] | None:
    if not group_id:
        return None
    group = await Group.get(parse_object_id(group_id))
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена.")
    return group.members


async def _filter_attempts(filters: dict[str, Any], current_user: User) -> list[Attempt]:
    query = _attempt_query(filters)
    member_ids = await _group_member_ids(filters.get("group_id"))
    if member_ids is not None:
        query["user_id"] = {"$in": member_ids}
    attempts = await Attempt.find(query).sort("-started_at").to_list()

    if current_user.role == UserRole.examiner:
        tests = await Test.find(Test.author_id == current_user.id).to_list()
        allowed_test_ids = {test.id for test in tests}
        attempts = [attempt for attempt in attempts if attempt.test_id in allowed_test_ids]
    return attempts


async def _user_map(attempts: list[Attempt]) -> dict[str, User]:
    ids = list({attempt.user_id for attempt in attempts})
    users = await User.find({"_id": {"$in": ids}}).to_list() if ids else []
    return {user.id: user for user in users}


async def _test_map(attempts: list[Attempt]) -> dict[str, Test]:
    ids = list({attempt.test_id for attempt in attempts})
    tests = await Test.find({"_id": {"$in": ids}}).to_list() if ids else []
    return {test.id: test for test in tests}


async def _group_map_for_users(user_ids: list[str]) -> dict[str, list[Group]]:
    groups = await Group.find_all().to_list()
    result: dict[str, list[Group]] = defaultdict(list)
    for group in groups:
        for user_id in user_ids:
            if user_id in group.members:
                result[user_id].append(group)
    return result


def _basic_stats(attempts: list[Attempt]) -> dict[str, Any]:
    finished = [attempt for attempt in attempts if attempt.status == AttemptStatus.finished]
    started = [attempt for attempt in attempts if attempt.status == AttemptStatus.started]
    passed = [attempt for attempt in finished if attempt.is_passed]
    failed = [attempt for attempt in finished if not attempt.is_passed]
    scores = [attempt.score for attempt in finished]
    percents = [attempt.percent for attempt in finished]
    durations = [
        (ensure_utc_aware(attempt.finished_at) - ensure_utc_aware(attempt.started_at)).total_seconds()
        for attempt in finished
        if attempt.finished_at
    ]
    return {
        "attempts_count": len(attempts),
        "started_count": len(started),
        "finished_count": len(finished),
        "passed_count": len(passed),
        "failed_count": len(failed),
        "average_score": round(sum(scores) / len(scores), 2) if scores else 0,
        "min_score": min(scores) if scores else 0,
        "max_score": max(scores) if scores else 0,
        "average_percent": round(sum(percents) / len(percents), 2) if percents else 0,
        "success_rate": round((len(passed) / len(finished)) * 100, 2) if finished else 0,
        "average_duration": format_seconds(round(sum(durations) / len(durations))) if durations else "00:00:00",
    }


def format_seconds(total_seconds: int) -> str:
    hours, remainder = divmod(max(total_seconds, 0), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


async def _next_report_number() -> str:
    year = utcnow().year
    prefix = f"RPT-{year}-"
    existing = await ReportRecord.find({"report_number": {"$regex": f"^{prefix}"}}).to_list()
    numbers = []
    for report in existing:
        try:
            numbers.append(int(report.report_number.rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    next_number = max(numbers, default=0) + 1
    while True:
        report_number = f"{prefix}{next_number:06d}"
        if not await ReportRecord.find_one(ReportRecord.report_number == report_number):
            return report_number
        next_number += 1


def _safe_report_path(report_number: str) -> Path:
    settings = get_settings()
    storage_dir = Path(settings.report_storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(char for char in report_number if char.isalnum() or char in "-_")
    return storage_dir / f"{safe_name}.pdf"


async def list_reports(user: User) -> list[ReportRecord]:
    if user.role == UserRole.admin:
        return await ReportRecord.find_all().sort("-created_at").to_list()
    return await ReportRecord.find(ReportRecord.generated_by == user.id).sort("-created_at").to_list()


async def get_report_or_404(report_id: str) -> ReportRecord:
    report = await ReportRecord.get(parse_object_id(report_id))
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Отчет не найден.")
    return report


async def get_report_by_number(report_number: str) -> ReportRecord | None:
    return await ReportRecord.find_one(ReportRecord.report_number == report_number)


async def _build_common_context(
    request: Request,
    report_number: str,
    title: str,
    report_type: ReportType,
    filters: dict[str, Any],
    options: dict[str, bool],
    generated_by: User,
) -> dict[str, Any]:
    verify_url = build_verify_url(str(request.base_url), report_number)
    qr_data_uri = make_qr_data_uri(verify_url) if options.get("include_qr") else None
    return {
        "report_number": report_number,
        "report_type": report_type.value,
        "title": title,
        "filters": filters,
        "options": options,
        "generated_by": generated_by,
        "created_at": utcnow(),
        "verify_url": verify_url,
        "qr_data_uri": qr_data_uri,
    }


async def _report_record(
    report_number: str,
    report_type: ReportType,
    title: str,
    filters: dict[str, Any],
    options: dict[str, bool],
    current_user: User,
    output_path: Path,
) -> ReportRecord:
    report = ReportRecord(
        report_number=report_number,
        type=report_type,
        title=title,
        filters={key: str(value) for key, value in filters.items()},
        options=options,
        test_id=filters.get("test_id"),
        user_id=filters.get("user_id"),
        group_id=filters.get("group_id"),
        private_link_id=filters.get("private_link_id"),
        generated_by=current_user.id,
        file_path=str(output_path),
    )
    await report.insert()
    return report


async def generate_report(payload: ReportCreateInput, current_user: User, request: Request) -> ReportRecord:
    filters = _clean_dict(payload.filters.model_dump())
    options = payload.options.model_dump()
    await can_generate_report(current_user, payload.report_type, filters)

    report_number = await _next_report_number()
    output_path = _safe_report_path(report_number)
    try:
        if payload.report_type == ReportType.test:
            context, title = await generate_test_report(filters, options, current_user)
        elif payload.report_type == ReportType.user:
            context, title = await generate_user_report(filters, options, current_user)
        elif payload.report_type == ReportType.group:
            context, title = await generate_group_report(filters, options, current_user)
        elif payload.report_type == ReportType.date:
            context, title = await generate_date_report(filters, options, current_user)
        elif payload.report_type == ReportType.private_link:
            context, title = await generate_private_link_report(filters, options, current_user)
        elif payload.report_type == ReportType.errors:
            context, title = await generate_errors_report(filters, options, current_user)
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неизвестный тип отчета.")

        common_context = await _build_common_context(
            request,
            report_number,
            title,
            payload.report_type,
            filters,
            options,
            current_user,
        )
        context.update(common_context)
        write_pdf(REPORT_TEMPLATES[payload.report_type], context, output_path)
        report = await _report_record(
            report_number,
            payload.report_type,
            title,
            filters,
            options,
            current_user,
            output_path,
        )
        await log_action(str(current_user.id), "create_report", "report", str(report.id), {"report_number": report_number})
        return report
    except HTTPException as exc:
        await log_action(str(current_user.id), "report_generation_error", "report", None, {"detail": str(exc.detail)})
        raise
    except Exception as exc:
        await log_action(str(current_user.id), "report_generation_error", "report", None, {"detail": str(exc)})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка генерации PDF.") from exc


async def generate_test_report(filters: dict[str, Any], options: dict[str, bool], current_user: User) -> tuple[dict, str]:
    test = await Test.get(parse_object_id(filters["test_id"]))
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тест не найден.")
    attempts = await _filter_attempts(filters, current_user)
    users = await _user_map(attempts)
    stats = _basic_stats(attempts)
    max_score = sum(question.points for question in test.questions)
    charts = {
        "pass_fail": pass_fail_chart(stats["passed_count"], stats["failed_count"]),
        "score_distribution": score_distribution(attempts),
    } if options.get("include_charts") else {}
    title = f"Отчет по тесту: {test.title}"
    return {
        "test": test,
        "author": await User.get(test.author_id),
        "attempts": attempts,
        "users": users,
        "stats": stats,
        "max_score": max_score,
        "charts": charts,
        "format_duration": format_duration,
    }, title


async def generate_user_report(filters: dict[str, Any], options: dict[str, bool], current_user: User) -> tuple[dict, str]:
    participant = await User.get(parse_object_id(filters["user_id"]))
    if not participant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден.")
    attempts = await _filter_attempts(filters, current_user)
    tests = await _test_map(attempts)
    groups = await _group_map_for_users([participant.id])
    stats = _basic_stats(attempts)
    title = f"Отчет по пользователю: {participant.full_name or participant.username}"
    return {
        "participant": participant,
        "groups": groups.get(participant.id, []),
        "attempts": attempts,
        "tests": tests,
        "stats": stats,
        "can_show_correct_answers": current_user.role in {UserRole.admin, UserRole.examiner},
        "charts": {"score_distribution": score_distribution(attempts)} if options.get("include_charts") else {},
    }, title


async def generate_group_report(filters: dict[str, Any], options: dict[str, bool], current_user: User) -> tuple[dict, str]:
    group = await Group.get(parse_object_id(filters["group_id"]))
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена.")
    attempts = await _filter_attempts(filters, current_user)
    users = await User.find({"_id": {"$in": group.members}}).to_list() if group.members else []
    attempts_by_user = {attempt.user_id: attempt for attempt in sorted(attempts, key=lambda item: item.started_at, reverse=True)}
    passed_users = [user for user in users if attempts_by_user.get(user.id) and attempts_by_user[user.id].is_passed]
    failed_users = [user for user in users if attempts_by_user.get(user.id) and not attempts_by_user[user.id].is_passed]
    not_started_users = [user for user in users if user.id not in attempts_by_user]
    stats = _basic_stats(attempts)
    title = f"Отчет по группе: {group.title}"
    return {
        "group": group,
        "users": users,
        "attempts_by_user": attempts_by_user,
        "passed_users": passed_users,
        "failed_users": failed_users,
        "not_started_users": not_started_users,
        "stats": stats,
        "charts": {"pass_fail": pass_fail_chart(len(passed_users), len(failed_users))} if options.get("include_charts") else {},
    }, title


async def generate_date_report(filters: dict[str, Any], options: dict[str, bool], current_user: User) -> tuple[dict, str]:
    attempts = await _filter_attempts(filters, current_user)
    users = await _user_map(attempts)
    tests = await _test_map(attempts)
    groups = await _group_map_for_users(list(users.keys()))
    stats = _basic_stats(attempts)
    title = f"Отчет по дате: {filters.get('date_from')} - {filters.get('date_to')}"
    return {
        "attempts": attempts,
        "users": users,
        "tests": tests,
        "groups": groups,
        "stats": stats,
        "unique_users_count": len({attempt.user_id for attempt in attempts}),
        "charts": {"score_distribution": score_distribution(attempts)} if options.get("include_charts") else {},
    }, title


async def generate_private_link_report(filters: dict[str, Any], options: dict[str, bool], current_user: User) -> tuple[dict, str]:
    link = await TestLink.get(parse_object_id(filters["private_link_id"]))
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Приватная ссылка не найдена.")
    test = await Test.get(link.test_id)
    attempts = await _filter_attempts(filters, current_user)
    users = await _user_map(attempts)
    stats = _basic_stats(attempts)
    title = f"Отчет по приватной ссылке: {test.title if test else link.token[:8]}"
    return {
        "link": link,
        "test": test,
        "creator": await User.get(link.created_by),
        "attempts": attempts,
        "users": users,
        "stats": stats,
        "masked_token": f"{link.token[:8]}...{link.token[-4:]}",
        "charts": {"pass_fail": pass_fail_chart(stats["passed_count"], stats["failed_count"])} if options.get("include_charts") else {},
    }, title


async def generate_errors_report(filters: dict[str, Any], options: dict[str, bool], current_user: User) -> tuple[dict, str]:
    test = await Test.get(parse_object_id(filters["test_id"]))
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тест не найден.")
    attempts = [attempt for attempt in await _filter_attempts(filters, current_user) if attempt.status == AttemptStatus.finished]
    question_texts = {question.id: question.text for question in test.questions}
    counters = {question.id: Counter(total=0, correct=0, wrong=0) for question in test.questions}
    for attempt in attempts:
        for answer in attempt.answers:
            if answer.question_id not in counters:
                continue
            counters[answer.question_id]["total"] += 1
            if answer.is_correct:
                counters[answer.question_id]["correct"] += 1
            else:
                counters[answer.question_id]["wrong"] += 1

    rows = []
    for question_id, counter in counters.items():
        total = counter["total"]
        wrong = counter["wrong"]
        rows.append(
            {
                "question": question_texts.get(question_id, "Вопрос удален"),
                "total_count": total,
                "correct_count": counter["correct"],
                "wrong_count": wrong,
                "error_percent": round((wrong / total) * 100, 2) if total else 0,
            }
        )
    rows.sort(key=lambda row: row["error_percent"], reverse=True)
    title = f"Отчет по ошибкам: {test.title}"
    return {
        "test": test,
        "attempts": attempts,
        "stats": _basic_stats(attempts),
        "question_rows": rows,
        "hardest_questions": rows[:5],
        "charts": {"question_errors": question_error_chart(rows)} if options.get("include_charts") else {},
    }, title

