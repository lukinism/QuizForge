from datetime import datetime

import random
from uuid import uuid4

from fastapi import HTTPException, status

from app.core.audit import log_action
from app.core.utils import ensure_utc_aware, parse_object_id, utcnow
from app.modules.groups.models import Group
from app.modules.tests.models import (
    Question,
    QuestionOption,
    QuestionType,
    Test,
    TestAssignment,
    TestLink,
    TestStatus,
    TestVisibility,
)
from app.modules.tests.schemas import QuestionInput, TestCreate, TestImport, TestLinkCreate, TestUpdate
from app.modules.users.models import User, UserRole


def _can_manage_test(user: User, test: Test) -> bool:
    return user.role == UserRole.admin or test.author_id == user.id


def _normalize_options(question_type: QuestionType, options_payload: list) -> list[QuestionOption]:
    options = [
        QuestionOption(
            text=option.text.strip(),
            is_correct=option.is_correct,
            match_text=option.match_text.strip(),
            order_index=option.order_index,
        )
        for option in options_payload
        if option.text.strip()
    ]

    choice_types = {
        QuestionType.single_choice,
        QuestionType.multiple_choice,
        QuestionType.image,
        QuestionType.audio,
        QuestionType.video,
        QuestionType.file,
    }
    if question_type in choice_types:
        if len(options) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="У вопроса с вариантами ответа должно быть минимум два варианта.",
            )
        correct_count = sum(option.is_correct for option in options)
        if question_type in {
            QuestionType.single_choice,
            QuestionType.image,
            QuestionType.audio,
            QuestionType.video,
            QuestionType.file,
        } and correct_count != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для вопроса с одним выбором нужно указать ровно один правильный ответ.",
            )
        if question_type == QuestionType.multiple_choice and correct_count < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для вопроса с множественным выбором нужен хотя бы один правильный ответ.",
            )

    if question_type in {
        QuestionType.text_answer,
        QuestionType.fill_blank,
        QuestionType.code,
    }:
        options = [option for option in options if option.is_correct]
    if question_type in {QuestionType.free_answer, QuestionType.practical}:
        options = []

    if question_type == QuestionType.matching:
        if len(options) < 2 or any(not option.match_text for option in options):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для задания на соответствие нужно минимум две пары: элемент и соответствие.",
            )

    if question_type == QuestionType.ordering:
        if len(options) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для сортировки нужно минимум два элемента.",
            )
        for index, option in enumerate(options, 1):
            option.order_index = option.order_index or index

    return options


def _build_question(payload: QuestionInput, question_id: str | None = None) -> Question:
    options = _normalize_options(payload.type, payload.options)
    if payload.type in {
        QuestionType.text_answer,
        QuestionType.fill_blank,
        QuestionType.code,
    } and not options:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для текстового вопроса нужно указать хотя бы один допустимый правильный ответ.",
        )
    if payload.type in {QuestionType.image, QuestionType.audio, QuestionType.video, QuestionType.file} and not payload.media_url.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для медиа-вопроса нужно указать ссылку на файл.",
        )
    if payload.type == QuestionType.code and not payload.code_snippet.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для вопроса с кодом нужно добавить фрагмент кода.",
        )
    return Question(
        id=question_id or str(uuid4()),
        type=payload.type,
        text=payload.text.strip(),
        points=payload.points,
        options=options,
        media_url=payload.media_url.strip(),
        code_language=payload.code_language.strip(),
        code_snippet=payload.code_snippet.strip(),
    )


async def get_test_or_404(test_id: str) -> Test:
    test = await Test.get(parse_object_id(test_id))
    if not test:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Тест не найден.")
    return test


async def get_manageable_test(test_id: str, user: User) -> Test:
    test = await get_test_or_404(test_id)
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    return test


async def list_manageable_tests(user: User) -> list[Test]:
    if user.role == UserRole.admin:
        return await Test.find_all().sort("-updated_at").to_list()
    return await Test.find(Test.author_id == user.id).sort("-updated_at").to_list()


async def delete_test_record(test: Test, user: User) -> None:
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    await TestLink.find(TestLink.test_id == test.id).delete()
    await TestAssignment.find(TestAssignment.test_id == test.id).delete()
    await test.delete()
    await log_action(str(user.id), "delete_test", "test", str(test.id), {"title": test.title})


async def list_public_tests() -> list[Test]:
    return await Test.find(
        Test.status == TestStatus.published,
        Test.visibility == TestVisibility.public,
    ).sort("-updated_at").to_list()


async def create_test(user: User, payload: TestCreate) -> Test:
    if user.role not in {UserRole.admin, UserRole.examiner}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    test = Test(
        title=payload.title.strip(),
        description=payload.description.strip(),
        author_id=user.id,
        visibility=payload.visibility,
        status=payload.status,
        settings=payload.settings,
    )
    await test.insert()
    await log_action(str(user.id), "create_test", "test", str(test.id), {"title": test.title})
    return test


async def import_test(user: User, payload: TestImport) -> Test:
    if user.role not in {UserRole.admin, UserRole.examiner}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    questions = [_build_question(question_payload) for question_payload in payload.questions]
    test = Test(
        title=payload.title.strip(),
        description=payload.description.strip(),
        author_id=user.id,
        visibility=payload.visibility,
        status=payload.status,
        settings=payload.settings,
        questions=questions,
    )
    await test.insert()
    await log_action(
        str(user.id),
        "import_test",
        "test",
        str(test.id),
        {"title": test.title, "questions_count": len(test.questions)},
    )
    return test


async def update_test(test: Test, user: User, payload: TestUpdate) -> Test:
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    test.title = payload.title.strip()
    test.description = payload.description.strip()
    test.visibility = payload.visibility
    test.status = payload.status
    test.settings = payload.settings
    test.updated_at = utcnow()
    await test.save()
    await log_action(str(user.id), "update_test", "test", str(test.id), {"title": test.title})
    return test


async def save_question(
    test: Test,
    user: User,
    payload: QuestionInput,
    question_id: str | None = None,
) -> Test:
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    question = _build_question(payload, question_id=question_id)
    updated_questions = []
    replaced = False

    for existing in test.questions:
        if existing.id == question.id:
            updated_questions.append(question)
            replaced = True
        else:
            updated_questions.append(existing)

    if not replaced:
        updated_questions.append(question)

    test.questions = updated_questions
    test.updated_at = utcnow()
    await test.save()
    action = "update_question" if replaced else "create_question"
    await log_action(
        str(user.id),
        action,
        "test_question",
        question.id,
        {"test_id": str(test.id)},
    )
    return test


async def delete_question(test: Test, user: User, question_id: str) -> Test:
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    question_exists = any(question.id == question_id for question in test.questions)
    if not question_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Вопрос не найден.")

    test.questions = [question for question in test.questions if question.id != question_id]
    test.updated_at = utcnow()
    await test.save()
    await log_action(
        str(user.id),
        "delete_question",
        "test_question",
        question_id,
        {"test_id": str(test.id)},
    )
    return test


async def create_private_link(test: Test, user: User, payload: TestLinkCreate) -> TestLink:
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    if test.status != TestStatus.published:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Приватную ссылку можно создать только для опубликованного теста.",
        )

    allowed_group_id = parse_object_id(payload.allowed_group_id) if payload.allowed_group_id else None
    allowed_user_ids = [parse_object_id(user_id) for user_id in payload.allowed_user_ids if user_id]

    if allowed_group_id:
        group = await Group.get(allowed_group_id)
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена.")

    link = TestLink(
        test_id=test.id,
        expires_at=payload.expires_at,
        max_uses=payload.max_uses,
        allowed_group_id=allowed_group_id,
        allowed_user_ids=allowed_user_ids,
        created_by=user.id,
    )
    await link.insert()
    await log_action(
        str(user.id),
        "create_test_link",
        "test_link",
        str(link.id),
        {"test_id": str(test.id), "token": link.token},
    )
    return link


async def list_test_links(test: Test, user: User) -> list[TestLink]:
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    return await TestLink.find(TestLink.test_id == test.id).sort("-created_at").to_list()


async def list_test_assignments(test: Test, user: User) -> list[TestAssignment]:
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    return await TestAssignment.find(TestAssignment.test_id == test.id).sort("-created_at").to_list()


async def create_test_assignment(test: Test, user: User, group_id: str) -> TestAssignment:
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    if test.status != TestStatus.published:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Выдать группе можно только опубликованный тест.",
        )

    group = await Group.get(parse_object_id(group_id))
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена.")
    if user.role != UserRole.admin and group.created_by != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")

    assignment = TestAssignment(test_id=test.id, group_id=group.id, created_by=user.id)
    await assignment.insert()
    await log_action(
        str(user.id),
        "create_test_assignment",
        "test_assignment",
        str(assignment.id),
        {"test_id": str(test.id), "group_id": str(group.id)},
    )
    return assignment


async def get_assignment_for_management(assignment_id: str, user: User) -> tuple[TestAssignment, Test, Group]:
    assignment = await TestAssignment.get(parse_object_id(assignment_id))
    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Выдача теста не найдена.")

    test = await get_test_or_404(assignment.test_id)
    group = await Group.get(assignment.group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Группа не найдена.")
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    if user.role != UserRole.admin and group.created_by != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    return assignment, test, group


async def get_assignment_for_student(assignment_id: str, user: User) -> tuple[TestAssignment, Test, Group]:
    if user.role != UserRole.student:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Прохождение тестов доступно только тестируемым.")

    assignment = await TestAssignment.get(parse_object_id(assignment_id))
    if not assignment or not assignment.is_active or assignment.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Выданный тест недоступен.")

    group = await Group.get(assignment.group_id)
    if not group or user.id not in group.members:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Вы не состоите в группе для этого теста.")
    if user.id in group.blocked_members or user.id in assignment.closed_user_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Этот тест для вас завершен проверяющим.")

    test = await get_test_or_404(assignment.test_id)
    if test.status != TestStatus.published:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Опубликованный тест не найден.")
    return assignment, test, group


async def list_assignments_for_student(user: User) -> list[TestAssignment]:
    groups = await Group.find({"members": user.id}).to_list()
    group_ids = [group.id for group in groups if user.id not in group.blocked_members]
    if not group_ids:
        return []
    assignments = await TestAssignment.find(
        {"group_id": {"$in": group_ids}, "is_active": True},
    ).sort("-created_at").to_list()
    return [
        assignment
        for assignment in assignments
        if assignment.ended_at is None and user.id not in assignment.closed_user_ids
    ]


async def close_assignment_for_user(assignment: TestAssignment, user: User, student_id: str) -> TestAssignment:
    assignment, _, _ = await get_assignment_for_management(assignment.id, user)
    parsed_student_id = parse_object_id(student_id)
    if parsed_student_id not in assignment.closed_user_ids:
        assignment.closed_user_ids.append(parsed_student_id)
        await assignment.save()
    await log_action(
        str(user.id),
        "close_test_assignment_for_user",
        "test_assignment",
        str(assignment.id),
        {"student_id": parsed_student_id},
    )
    return assignment


async def close_assignment_for_group(assignment: TestAssignment, user: User) -> TestAssignment:
    assignment, _, group = await get_assignment_for_management(assignment.id, user)
    assignment.is_active = False
    assignment.ended_at = utcnow()
    assignment.closed_user_ids = list(set(assignment.closed_user_ids + group.members))
    await assignment.save()
    await log_action(
        str(user.id),
        "close_test_assignment_for_group",
        "test_assignment",
        str(assignment.id),
        {"group_id": str(group.id)},
    )
    return assignment


async def validate_test_link(token: str, user: User) -> tuple[TestLink, Test]:
    from app.modules.attempts.models import Attempt, AttemptStatus

    link = await TestLink.find_one(TestLink.token == token)
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Приватная ссылка не найдена.")

    test = await Test.get(link.test_id)
    if not test or test.status != TestStatus.published:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Опубликованный тест не найден.")

    existing_attempt = await Attempt.find_one(
        {
            "test_link_id": link.id,
            "user_id": user.id,
            "status": {"$in": [AttemptStatus.started, AttemptStatus.revision_requested]},
        },
    )
    if existing_attempt:
        return link, test

    if not link.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Эта приватная ссылка отключена.")
    expires_at = ensure_utc_aware(link.expires_at)
    if expires_at and expires_at < utcnow():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Срок действия приватной ссылки истек.")
    if link.max_uses is not None and link.used_count >= link.max_uses:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Лимит использований приватной ссылки исчерпан.")

    if link.allowed_user_ids and user.id not in link.allowed_user_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="У вас нет доступа по этой приватной ссылке.")

    if link.allowed_group_id:
        group = await Group.get(link.allowed_group_id)
        if not group or user.id not in group.members:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Вы не входите в разрешенную группу для этого теста.")

    return link, test


async def get_public_test_for_student(test_id: str) -> Test:
    test = await get_test_or_404(test_id)
    if test.status != TestStatus.published or test.visibility != TestVisibility.public:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Этот тест сейчас недоступен для публичного прохождения.")
    return test


def shuffle_question_for_attempt(test: Test) -> list[Question]:
    questions = list(test.questions)
    if test.settings.shuffle_questions:
        random.shuffle(questions)
    shuffled_questions: list[Question] = []
    for question in questions:
        options = list(question.options)
        if test.settings.shuffle_answers:
            random.shuffle(options)
        shuffled_questions.append(
            Question(
                id=question.id,
                type=question.type,
                text=question.text,
                points=question.points,
                options=options,
                media_url=question.media_url,
                code_language=question.code_language,
                code_snippet=question.code_snippet,
            )
        )
    return shuffled_questions


async def consume_link(link: TestLink) -> TestLink:
    link.used_count += 1
    await link.save()
    return link


async def get_authorized_test_for_results(test_id: str, user: User) -> Test:
    test = await get_test_or_404(test_id)
    if not _can_manage_test(user, test):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Доступ к этому разделу запрещен.")
    return test
