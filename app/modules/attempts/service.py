from fastapi import HTTPException, status

from app.core.audit import log_action
from app.core.utils import ensure_utc_aware, parse_object_id, utcnow
from app.modules.attempts.models import Attempt, AttemptAnswer, AttemptOptionSnapshot, AttemptStatus
from app.modules.groups.models import Group
from app.modules.tests.models import QuestionType, Test, TestAssignment, TestLink
from app.modules.tests.service import consume_link, shuffle_question_for_attempt
from app.modules.users.models import User, UserRole


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


MANUAL_REVIEW_TYPES = {QuestionType.free_answer, QuestionType.practical}
COMPLETED_ATTEMPT_STATUSES = {
    AttemptStatus.finished,
    AttemptStatus.expired,
    AttemptStatus.terminated,
}


def _requires_manual_review(answer: AttemptAnswer) -> bool:
    return answer.question_type in MANUAL_REVIEW_TYPES


def _grade_answer(answer: AttemptAnswer) -> tuple[bool, float]:
    if _requires_manual_review(answer):
        return False, 0

    choice_types = {
        QuestionType.single_choice,
        QuestionType.multiple_choice,
        QuestionType.image,
        QuestionType.audio,
        QuestionType.video,
        QuestionType.file,
    }
    if answer.question_type in choice_types:
        correct_ids = {option.id for option in answer.options if option.is_correct}
        selected_ids = set(answer.selected_options)
        is_correct = selected_ids == correct_ids and bool(correct_ids)
        return is_correct, answer.max_points if is_correct else 0

    if answer.question_type == QuestionType.matching:
        submitted_pairs = {}
        for value in answer.selected_options:
            if "::" not in value:
                continue
            option_id, selected_match = value.split("::", 1)
            submitted_pairs[option_id] = _normalize_text(selected_match)
        is_correct = bool(answer.options) and all(
            submitted_pairs.get(option.id) == _normalize_text(option.match_text)
            for option in answer.options
        )
        return is_correct, answer.max_points if is_correct else 0

    if answer.question_type == QuestionType.ordering:
        submitted_order = {}
        for value in answer.selected_options:
            if "::" not in value:
                continue
            option_id, selected_order = value.split("::", 1)
            if selected_order.isdigit():
                submitted_order[option_id] = int(selected_order)
        is_correct = bool(answer.options) and all(
            submitted_order.get(option.id) == option.order_index
            for option in answer.options
        )
        return is_correct, answer.max_points if is_correct else 0

    if answer.question_type in {
        QuestionType.text_answer,
        QuestionType.free_answer,
        QuestionType.fill_blank,
        QuestionType.code,
        QuestionType.practical,
    }:
        correct_texts = {_normalize_text(option.text) for option in answer.options if option.is_correct}
        is_correct = _normalize_text(answer.text_answer) in correct_texts and bool(correct_texts)
        return is_correct, answer.max_points if is_correct else 0

    return False, 0


def _can_view_attempt(user: User, attempt: Attempt, owned_test_ids: set | None = None) -> bool:
    if user.role == UserRole.admin:
        return True
    if user.role == UserRole.student:
        return attempt.user_id == user.id
    return owned_test_ids is not None and attempt.test_id in owned_test_ids


async def sync_attempt_snapshot_from_test(attempt: Attempt, test: Test) -> Attempt:
    questions_by_id = {question.id: question for question in test.questions}
    changed = False

    for answer in attempt.answers:
        question = questions_by_id.get(answer.question_id)
        if not question:
            continue

        if not answer.media_url and question.media_url:
            answer.media_url = question.media_url
            changed = True
        if not answer.code_language and question.code_language:
            answer.code_language = question.code_language
            changed = True
        if not answer.code_snippet and question.code_snippet:
            answer.code_snippet = question.code_snippet
            changed = True
        requires_manual_review = question.type in MANUAL_REVIEW_TYPES
        if answer.requires_manual_review != requires_manual_review:
            answer.requires_manual_review = requires_manual_review
            changed = True

        options_by_id = {option.id: option for option in question.options}
        for snapshot in answer.options:
            option = options_by_id.get(snapshot.id)
            if not option:
                continue
            if not snapshot.match_text and option.match_text:
                snapshot.match_text = option.match_text
                changed = True
            if snapshot.order_index is None and option.order_index is not None:
                snapshot.order_index = option.order_index
                changed = True

    if changed:
        await attempt.save()
    return attempt


async def _get_examiner_test_ids(user: User) -> set:
    from app.modules.tests.models import Test

    tests = await Test.find(Test.author_id == user.id).to_list()
    return {test.id for test in tests}


async def get_or_create_attempt(
    test: Test,
    user: User,
    link: TestLink | None = None,
    assignment: TestAssignment | None = None,
) -> Attempt:
    if user.role != UserRole.student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Прохождение тестов доступно только тестируемым.",
        )
    if not test.questions:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="В тесте пока нет вопросов.")
    if assignment:
        if not assignment.is_active or assignment.ended_at is not None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Выдача этого теста уже завершена.")
        if user.id in assignment.closed_user_ids:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Этот тест для вас завершен проверяющим.")

    existing_query = {
        "test_id": test.id,
        "user_id": user.id,
        "status": {"$in": [AttemptStatus.started, AttemptStatus.revision_requested]},
    }
    if assignment:
        existing_query["assignment_id"] = assignment.id
    existing_attempt = await Attempt.find_one(existing_query)
    if existing_attempt:
        if existing_attempt.time_limit_minutes is not None:
            from datetime import timedelta

            started_at = ensure_utc_aware(existing_attempt.started_at)
            deadline = started_at + timedelta(minutes=existing_attempt.time_limit_minutes)
            if existing_attempt.status == AttemptStatus.started and utcnow() >= deadline:
                await mark_attempt_expired(existing_attempt)
            else:
                return await sync_attempt_snapshot_from_test(existing_attempt, test)
        else:
            return await sync_attempt_snapshot_from_test(existing_attempt, test)

    attempts_count_query = {
        "test_id": test.id,
        "user_id": user.id,
    }
    if assignment:
        attempts_count_query["assignment_id"] = assignment.id
    attempts_count = await Attempt.find(attempts_count_query).count()
    if attempts_count >= test.settings.max_attempts:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Лимит попыток для этого теста уже исчерпан.")

    questions = shuffle_question_for_attempt(test)
    answers = [
        AttemptAnswer(
            question_id=question.id,
            question_text=question.text,
            question_type=question.type,
            selected_options=[],
            text_answer="",
            points_received=0,
            max_points=question.points,
            options=[
                AttemptOptionSnapshot(
                    id=option.id,
                    text=option.text,
                    is_correct=option.is_correct,
                    match_text=option.match_text,
                    order_index=option.order_index,
                )
                for option in question.options
            ],
            media_url=question.media_url,
            code_language=question.code_language,
            code_snippet=question.code_snippet,
            requires_manual_review=question.type in MANUAL_REVIEW_TYPES,
            manual_reviewed=False,
            review_comment="",
        )
        for question in questions
    ]

    attempt = Attempt(
        test_id=test.id,
        test_title=test.title,
        user_id=user.id,
        test_link_id=link.id if link else None,
        assignment_id=assignment.id if assignment else None,
        time_limit_minutes=test.settings.time_limit_minutes,
        show_result=test.settings.show_result,
        show_correct_answers=test.settings.show_correct_answers,
        max_score=sum(answer.max_points for answer in answers),
        passing_score=test.settings.passing_score,
        answers=answers,
    )
    await attempt.insert()
    if link:
        await consume_link(link)
    await log_action(
        str(user.id),
        "start_attempt",
        "attempt",
        str(attempt.id),
        {"test_id": str(test.id)},
    )
    return attempt


async def mark_attempt_expired(attempt: Attempt) -> Attempt:
    attempt.status = AttemptStatus.expired
    attempt.finished_at = utcnow()
    attempt.percent = 0
    attempt.is_passed = False
    await attempt.save()
    if attempt.assignment_id:
        await close_assignment_if_all_members_done(attempt.assignment_id)
    return attempt


async def terminate_attempt(attempt: Attempt, actor: User | None = None) -> Attempt:
    if attempt.status != AttemptStatus.started:
        return attempt
    attempt.status = AttemptStatus.terminated
    attempt.finished_at = utcnow()
    attempt.percent = round((attempt.score / attempt.max_score) * 100, 2) if attempt.max_score else 0
    attempt.is_passed = False
    await attempt.save()
    await log_action(
        str(actor.id) if actor else None,
        "terminate_attempt",
        "attempt",
        str(attempt.id),
        {"test_id": str(attempt.test_id), "user_id": str(attempt.user_id)},
    )
    if attempt.assignment_id:
        await close_assignment_if_all_members_done(attempt.assignment_id)
    return attempt


async def close_assignment_if_all_members_done(assignment_id: str) -> TestAssignment | None:
    assignment = await TestAssignment.get(assignment_id)
    if not assignment or not assignment.is_active or assignment.ended_at is not None:
        return assignment

    group = await Group.get(assignment.group_id)
    if not group:
        return assignment

    participant_ids = [
        member_id
        for member_id in group.members
        if member_id not in group.blocked_members
    ]
    if not participant_ids:
        return assignment

    attempts = await Attempt.find(
        {"assignment_id": assignment.id, "user_id": {"$in": participant_ids}},
    ).sort("-started_at").to_list()
    latest_attempts = {}
    for attempt in attempts:
        latest_attempts.setdefault(attempt.user_id, attempt)

    all_done = all(
        member_id in assignment.closed_user_ids
        or (
            latest_attempts.get(member_id) is not None
            and latest_attempts[member_id].status in COMPLETED_ATTEMPT_STATUSES
        )
        for member_id in participant_ids
    )
    if not all_done:
        return assignment

    assignment.is_active = False
    assignment.ended_at = utcnow()
    assignment.closed_user_ids = list(set(assignment.closed_user_ids + participant_ids))
    await assignment.save()
    await log_action(
        None,
        "auto_close_test_assignment",
        "test_assignment",
        str(assignment.id),
        {"group_id": str(group.id)},
    )
    return assignment


async def submit_attempt(attempt: Attempt, submitted_answers: dict[str, dict[str, list[str] | str]]) -> Attempt:
    is_revision = attempt.status == AttemptStatus.revision_requested
    if attempt.status not in {AttemptStatus.started, AttemptStatus.revision_requested}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Эта попытка уже завершена.")

    updated_answers: list[AttemptAnswer] = []
    needs_manual_review = False

    for answer in attempt.answers:
        if is_revision and not answer.requires_manual_review:
            updated_answers.append(answer)
            continue

        submitted = submitted_answers.get(answer.question_id, {})
        selected_options = [
            option_id
            for option_id in submitted.get("selected_options", [])
            if option_id in {option.id for option in answer.options}
        ]
        text_answer = str(submitted.get("text_answer", "")).strip()

        answer.selected_options = selected_options
        answer.text_answer = text_answer
        answer.requires_manual_review = _requires_manual_review(answer)
        if answer.requires_manual_review:
            answer.is_correct = None
            answer.points_received = 0
            answer.manual_reviewed = False
            needs_manual_review = True
        else:
            answer.is_correct, answer.points_received = _grade_answer(answer)
            answer.manual_reviewed = True
        updated_answers.append(answer)

    attempt.answers = updated_answers
    auto_score = sum(answer.points_received for answer in updated_answers if not answer.requires_manual_review)
    attempt.score = round(auto_score, 2)
    attempt.finished_at = utcnow()
    attempt.status = AttemptStatus.pending_review if needs_manual_review else AttemptStatus.finished
    attempt.percent = round((attempt.score / attempt.max_score) * 100, 2) if attempt.max_score else 0
    attempt.is_passed = False if needs_manual_review else attempt.percent >= attempt.passing_score
    await attempt.save()
    await log_action(
        str(attempt.user_id),
        "submit_attempt",
        "attempt",
        str(attempt.id),
        {"score": attempt.score, "percent": attempt.percent},
    )
    if attempt.assignment_id and attempt.status == AttemptStatus.finished:
        await close_assignment_if_all_members_done(attempt.assignment_id)
    return attempt


def _recalculate_attempt_result(attempt: Attempt) -> Attempt:
    attempt.score = round(sum(answer.points_received for answer in attempt.answers), 2)
    attempt.percent = round((attempt.score / attempt.max_score) * 100, 2) if attempt.max_score else 0
    attempt.is_passed = attempt.percent >= attempt.passing_score
    return attempt


async def review_manual_answer(
    attempt: Attempt,
    question_id: str,
    points: float,
    comment: str,
    actor: User,
) -> Attempt:
    if attempt.status not in {AttemptStatus.pending_review, AttemptStatus.revision_requested}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Эта попытка не находится на ручной проверке.")
    if points < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Баллы не могут быть отрицательными.")

    updated = False
    for answer in attempt.answers:
        if answer.question_id != question_id:
            continue
        if not answer.requires_manual_review:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Этот ответ не требует ручной проверки.")
        if points > answer.max_points:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Баллы не могут превышать максимум за вопрос.")
        answer.points_received = round(points, 2)
        answer.review_comment = comment.strip()
        answer.manual_reviewed = True
        answer.is_correct = answer.points_received >= answer.max_points
        updated = True
        break

    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ответ не найден.")

    _recalculate_attempt_result(attempt)
    await attempt.save()
    await log_action(
        str(actor.id),
        "review_manual_answer",
        "attempt",
        str(attempt.id),
        {"question_id": question_id, "points": points},
    )
    return attempt


async def request_attempt_revision(attempt: Attempt, comment: str, actor: User) -> Attempt:
    if attempt.status != AttemptStatus.pending_review:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="На доработку можно отправить только попытку на проверке.")

    for answer in attempt.answers:
        if answer.requires_manual_review and comment.strip():
            answer.review_comment = comment.strip()
    attempt.status = AttemptStatus.revision_requested
    attempt.finished_at = None
    attempt.is_passed = False
    await attempt.save()
    await log_action(
        str(actor.id),
        "request_attempt_revision",
        "attempt",
        str(attempt.id),
        {"comment": comment.strip()},
    )
    return attempt


async def confirm_attempt_final_score(attempt: Attempt, actor: User) -> Attempt:
    if attempt.status != AttemptStatus.pending_review:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Подтвердить можно только попытку на проверке.")
    unreviewed_answers = [
        answer for answer in attempt.answers
        if answer.requires_manual_review and not answer.manual_reviewed
    ]
    if unreviewed_answers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Сначала оцените все ответы, требующие ручной проверки.")

    _recalculate_attempt_result(attempt)
    attempt.status = AttemptStatus.finished
    attempt.finished_at = attempt.finished_at or utcnow()
    await attempt.save()
    await log_action(
        str(actor.id),
        "confirm_attempt_final_score",
        "attempt",
        str(attempt.id),
        {"score": attempt.score, "percent": attempt.percent},
    )
    if attempt.assignment_id:
        await close_assignment_if_all_members_done(attempt.assignment_id)
    return attempt


async def get_attempt_for_user(attempt_id: str, user: User) -> Attempt:
    attempt = await Attempt.get(parse_object_id(attempt_id))
    if not attempt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Попытка не найдена.")

    owned_test_ids = None
    if user.role == UserRole.examiner:
        owned_test_ids = await _get_examiner_test_ids(user)

    if not _can_view_attempt(user, attempt, owned_test_ids):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    return attempt


async def list_attempts_for_scope(user: User) -> list[Attempt]:
    if user.role == UserRole.admin:
        return await Attempt.find_all().sort("-started_at").to_list()
    if user.role == UserRole.student:
        return await Attempt.find(Attempt.user_id == user.id).sort("-started_at").to_list()

    owned_test_ids = list(await _get_examiner_test_ids(user))
    if not owned_test_ids:
        return []
    return await Attempt.find({"test_id": {"$in": owned_test_ids}}).sort("-started_at").to_list()


async def list_attempts_for_test(test_id: str) -> list[Attempt]:
    object_id = parse_object_id(test_id)
    return await Attempt.find(Attempt.test_id == object_id).sort("-started_at").to_list()


async def latest_attempts_by_user(test_id: str, user_ids: list) -> dict:
    attempts = await Attempt.find({"test_id": test_id, "user_id": {"$in": user_ids}}).sort("-started_at").to_list()
    grouped = {}
    for attempt in attempts:
        grouped.setdefault(attempt.user_id, attempt)
    return grouped


async def latest_attempts_by_assignment(assignment_id: str, user_ids: list) -> dict:
    attempts = await Attempt.find(
        {"assignment_id": assignment_id, "user_id": {"$in": user_ids}},
    ).sort("-started_at").to_list()
    grouped = {}
    for attempt in attempts:
        grouped.setdefault(attempt.user_id, attempt)
    return grouped
