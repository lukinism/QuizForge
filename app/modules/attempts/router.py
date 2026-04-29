from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.dependencies import require_roles
from app.core.templates import templates
from app.core.utils import ensure_utc_aware, utcnow
from app.modules.attempts.models import AttemptStatus
from app.modules.attempts.service import (
    confirm_attempt_final_score,
    get_attempt_for_user,
    list_attempts_for_scope,
    mark_attempt_expired,
    request_attempt_revision,
    review_manual_answer,
    submit_attempt,
    sync_attempt_snapshot_from_test,
)
from app.modules.tests.models import Test
from app.modules.users.models import User, UserRole


router = APIRouter(prefix="/attempts", tags=["attempts"])


def _time_is_over(attempt) -> bool:
    if attempt.time_limit_minutes is None:
        return False
    started_at = ensure_utc_aware(attempt.started_at)
    deadline = started_at + timedelta(minutes=attempt.time_limit_minutes)
    return utcnow() >= deadline


@router.get("")
async def attempts_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner, UserRole.student)),
):
    attempts = await list_attempts_for_scope(current_user)
    user_map = {}
    test_map = {}
    if attempts:
        users = await User.find({"_id": {"$in": list({attempt.user_id for attempt in attempts})}}).to_list()
        tests = await Test.find({"_id": {"$in": list({attempt.test_id for attempt in attempts})}}).to_list()
        user_map = {user.id: user for user in users}
        test_map = {test.id: test for test in tests}
    template_name = {
        UserRole.admin: "admin/results.html",
        UserRole.examiner: "examiner/results.html",
        UserRole.student: "student/results.html",
    }[current_user.role]
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "current_user": current_user,
            "attempts": attempts,
            "user_map": user_map,
            "test_map": test_map,
        },
    )


@router.get("/{attempt_id}")
async def attempt_detail_page(
    attempt_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner, UserRole.student)),
):
    attempt = await get_attempt_for_user(attempt_id, current_user)
    test = await Test.get(attempt.test_id)
    if test:
        attempt = await sync_attempt_snapshot_from_test(attempt, test)
    participant = await User.get(attempt.user_id)
    results_hidden = current_user.role == UserRole.student and not attempt.show_result
    show_correct_answers = current_user.role != UserRole.student or attempt.show_correct_answers
    return templates.TemplateResponse(
        request=request,
        name="student/attempt_detail.html" if current_user.role == UserRole.student else "examiner/attempt_detail.html",
        context={
            "current_user": current_user,
            "attempt": attempt,
            "test": test,
            "participant": participant,
            "results_hidden": results_hidden,
            "show_correct_answers": show_correct_answers,
        },
    )


@router.post("/{attempt_id}/submit")
async def submit_attempt_form(
    attempt_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    attempt = await get_attempt_for_user(attempt_id, current_user)
    test = await Test.get(attempt.test_id)
    if test:
        attempt = await sync_attempt_snapshot_from_test(attempt, test)
    if attempt.status == AttemptStatus.started and _time_is_over(attempt):
        await mark_attempt_expired(attempt)
        return RedirectResponse(url=f"/attempts/{attempt_id}", status_code=303)

    form = await request.form()
    submitted_answers = {}
    for answer in attempt.answers:
        submitted_answers[answer.question_id] = {
            "selected_options": form.getlist(f"question_{answer.question_id}") + form.getlist(f"match_{answer.question_id}") + form.getlist(f"order_{answer.question_id}"),
            "text_answer": str(form.get(f"text_{answer.question_id}", "")),
        }
    await submit_attempt(attempt, submitted_answers)
    return RedirectResponse(url=f"/attempts/{attempt_id}", status_code=303)


@router.post("/{attempt_id}/answers/{question_id}/review")
async def review_manual_answer_submit(
    attempt_id: str,
    question_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    points: float = Form(...),
    comment: str = Form(""),
):
    attempt = await get_attempt_for_user(attempt_id, current_user)
    await review_manual_answer(attempt, question_id, points, comment, current_user)
    return RedirectResponse(url=f"/attempts/{attempt_id}", status_code=303)


@router.post("/{attempt_id}/request-revision")
async def request_attempt_revision_submit(
    attempt_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    comment: str = Form(""),
):
    attempt = await get_attempt_for_user(attempt_id, current_user)
    await request_attempt_revision(attempt, comment, current_user)
    return RedirectResponse(url=f"/attempts/{attempt_id}", status_code=303)


@router.post("/{attempt_id}/confirm")
async def confirm_attempt_final_score_submit(
    attempt_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    attempt = await get_attempt_for_user(attempt_id, current_user)
    await confirm_attempt_final_score(attempt, current_user)
    return RedirectResponse(url=f"/attempts/{attempt_id}", status_code=303)


@router.get("/{attempt_id}/status")
async def attempt_status(
    attempt_id: str,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    attempt = await get_attempt_for_user(attempt_id, current_user)
    return JSONResponse(
        {
            "status": attempt.status.value,
            "detail_url": f"/attempts/{attempt.id}",
        },
    )
