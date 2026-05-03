import json
import zipfile
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.core.config import get_settings
from app.core.dependencies import require_roles
from app.core.templates import templates
from app.core.utils import ensure_utc_aware, utcnow
from app.modules.attempts.models import AttemptStatus
from app.modules.attempts.service import (
    close_assignment_if_all_members_done,
    get_or_create_attempt,
    latest_attempts_by_assignment,
    terminate_attempt,
)
from app.modules.groups.service import list_groups
from app.modules.tests.models import QuestionType, Test, TestFlowMode, TestSettings, TestStatus, TestVisibility
from app.modules.tests.schemas import OptionInput, QuestionInput, TestCreate, TestImport, TestLinkCreate, TestUpdate
from app.modules.tests.service import (
    close_assignment_for_group,
    close_assignment_for_user,
    create_private_link,
    create_test,
    create_test_assignment,
    delete_question,
    delete_test_record,
    get_assignment_for_management,
    get_assignment_for_student,
    get_manageable_test,
    get_public_test_for_student,
    import_test,
    list_assignments_for_student,
    list_manageable_tests,
    list_public_tests,
    list_test_assignments,
    list_test_links,
    save_question,
    update_test,
    validate_test_link,
)
from app.modules.users.models import User, UserRole
from app.modules.users.service import list_users


router = APIRouter(prefix="/tests", tags=["tests"])

MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
MEDIA_QUESTION_TYPES = {QuestionType.image, QuestionType.audio, QuestionType.video, QuestionType.file}
MEDIA_EXTENSIONS_BY_TYPE = {
    QuestionType.image: {".apng", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"},
    QuestionType.audio: {".m4a", ".mp3", ".ogg", ".wav"},
    QuestionType.video: {".avi", ".mkv", ".mov", ".mp4", ".webm"},
}
FILE_EXTENSIONS = {
    ".apng",
    ".avi",
    ".bmp",
    ".csv",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".pdf",
    ".png",
    ".pptx",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".xlsx",
}
TEXT_FILE_EXTENSIONS = {".csv", ".txt"}
OFFICE_FILE_EXTENSIONS = {".docx", ".pptx", ".xlsx"}
OFFICE_REQUIRED_ENTRIES = {
    ".docx": "word/",
    ".pptx": "ppt/",
    ".xlsx": "xl/",
}
OFFICE_BLOCKED_ENTRY_PARTS = {
    "activex",
    "embeddings",
    "vbaproject.bin",
}


def _manager_template(current_user: User, page: str) -> str:
    folder = "admin" if current_user.role == UserRole.admin else "examiner"
    return f"{folder}/{page}.html"


def _remaining_seconds(attempt) -> int | None:
    if attempt.time_limit_minutes is None:
        return None
    started_at = ensure_utc_aware(attempt.started_at)
    deadline = started_at + timedelta(minutes=attempt.time_limit_minutes)
    return max(int((deadline - utcnow()).total_seconds()), 0)


def _visible_answers_for_take(attempt):
    if attempt.status == AttemptStatus.revision_requested:
        return [answer for answer in attempt.answers if answer.requires_manual_review]
    return attempt.answers


def _build_test_payload(
    title: str,
    description: str,
    visibility: TestVisibility,
    status: TestStatus,
    time_limit_minutes: str,
    max_attempts: int,
    passing_score: int,
    show_result: bool,
    show_correct_answers: bool,
    shuffle_questions: bool,
    shuffle_answers: bool,
    instruction_enabled: bool,
    instruction_text: str,
    flow_mode: TestFlowMode,
    allow_question_skip: bool,
) -> TestCreate:
    settings = TestSettings(
        time_limit_minutes=int(time_limit_minutes) if time_limit_minutes.strip() else None,
        max_attempts=max_attempts,
        passing_score=passing_score,
        show_result=show_result,
        show_correct_answers=show_correct_answers,
        shuffle_questions=shuffle_questions,
        shuffle_answers=shuffle_answers,
        instruction_enabled=instruction_enabled,
        instruction_text=instruction_text.strip() if instruction_enabled else "",
        flow_mode=flow_mode,
        allow_question_skip=allow_question_skip,
    )
    return TestCreate(
        title=title,
        description=description,
        visibility=visibility,
        status=status,
        settings=settings,
    )


def _format_validation_error(exc: ValidationError) -> str:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first_error.get("loc", []))
    message = first_error.get("msg", "Проверьте структуру JSON.")
    return f"{location}: {message}" if location else message


def _edit_redirect_url(test_id: str, message: str, anchor: str = "") -> str:
    query = urlencode({"toast": message, "toast_level": "success"})
    fragment = f"#{anchor}" if anchor else ""
    return f"/tests/{test_id}/edit?{query}{fragment}"


def _read_file_start(path: Path, size: int = 8192) -> bytes:
    with path.open("rb") as file:
        return file.read(size)


def _is_text_file(path: Path) -> bool:
    sample = _read_file_start(path)
    if b"\x00" in sample:
        return False
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            sample.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def _is_supported_image(path: Path, extension: str) -> bool:
    header = _read_file_start(path, 32)
    signatures = {
        ".bmp": (b"BM",),
        ".gif": (b"GIF87a", b"GIF89a"),
        ".jpeg": (b"\xff\xd8\xff",),
        ".jpg": (b"\xff\xd8\xff",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".apng": (b"\x89PNG\r\n\x1a\n",),
        ".webp": (b"RIFF",),
    }
    if not header.startswith(signatures.get(extension, ())):
        return False
    if extension == ".webp":
        return header[8:12] == b"WEBP"
    return True


def _is_supported_audio(path: Path, extension: str) -> bool:
    header = _read_file_start(path, 32)
    if extension == ".mp3":
        return header.startswith(b"ID3") or (len(header) > 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)
    if extension == ".wav":
        return header.startswith(b"RIFF") and header[8:12] == b"WAVE"
    if extension == ".ogg":
        return header.startswith(b"OggS")
    if extension == ".m4a":
        return b"ftyp" in header[4:12]
    return False


def _is_supported_video(path: Path, extension: str) -> bool:
    header = _read_file_start(path, 32)
    if extension in {".mp4", ".mov"}:
        return b"ftyp" in header[4:12]
    if extension == ".webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if extension == ".mkv":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if extension == ".avi":
        return header.startswith(b"RIFF") and header[8:12] == b"AVI "
    return False


def _is_safe_pdf(path: Path) -> bool:
    header = _read_file_start(path, 8)
    if not header.startswith(b"%PDF-"):
        return False
    content = path.read_bytes().lower()
    blocked_markers = [
        b"/aa",
        b"/embeddedfile",
        b"/javascript",
        b"/js",
        b"/launch",
        b"/openaction",
        b"/richmedia",
    ]
    return not any(marker in content for marker in blocked_markers)


def _is_safe_office_document(path: Path, extension: str) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename.lower() for entry in entries]
    except zipfile.BadZipFile:
        return False

    if len(entries) > 500:
        return False
    if sum(entry.file_size for entry in entries) > MAX_UPLOAD_SIZE_BYTES * 2:
        return False

    required_entry = OFFICE_REQUIRED_ENTRIES[extension]
    if not any(name.startswith(required_entry) for name in names):
        return False
    return not any(
        blocked_part in name
        for name in names
        for blocked_part in OFFICE_BLOCKED_ENTRY_PARTS
    )


def _uploaded_file_matches_type(path: Path, extension: str, question_type: QuestionType) -> bool:
    if question_type == QuestionType.image:
        return _is_supported_image(path, extension)
    if question_type == QuestionType.audio:
        return _is_supported_audio(path, extension)
    if question_type == QuestionType.video:
        return _is_supported_video(path, extension)
    if question_type != QuestionType.file:
        return False

    if extension in MEDIA_EXTENSIONS_BY_TYPE[QuestionType.image]:
        return _is_supported_image(path, extension)
    if extension in MEDIA_EXTENSIONS_BY_TYPE[QuestionType.audio]:
        return _is_supported_audio(path, extension)
    if extension in MEDIA_EXTENSIONS_BY_TYPE[QuestionType.video]:
        return _is_supported_video(path, extension)
    if extension in TEXT_FILE_EXTENSIONS:
        return _is_text_file(path)
    if extension == ".pdf":
        return _is_safe_pdf(path)
    if extension in OFFICE_FILE_EXTENSIONS:
        return _is_safe_office_document(path, extension)
    return False


async def _save_uploaded_media(upload: UploadFile, question_type: QuestionType) -> str:
    if question_type not in MEDIA_QUESTION_TYPES or not upload.filename:
        return ""

    extension = Path(upload.filename).suffix.lower()
    allowed_extensions = MEDIA_EXTENSIONS_BY_TYPE.get(question_type, FILE_EXTENSIONS)
    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот формат файла не поддерживается для загрузки.",
        )

    settings = get_settings()
    filename = f"{uuid4().hex}{extension}"
    destination = settings.upload_storage_dir / filename
    temporary_destination = settings.upload_storage_dir / f".{filename}.uploading"

    total_size = 0
    has_content = False
    try:
        with temporary_destination.open("wb") as file:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                has_content = True
                total_size += len(chunk)
                if total_size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Файл слишком большой. Максимальный размер: 50 МБ.",
                    )
                file.write(chunk)

        if not has_content:
            return ""
        if not _uploaded_file_matches_type(temporary_destination, extension, question_type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Файл не прошел проверку безопасности или не соответствует выбранному типу вопроса.",
            )

        temporary_destination.replace(destination)
    finally:
        temporary_destination.unlink(missing_ok=True)
    return f"/uploads/{filename}"


async def _build_question_payload(request: Request) -> QuestionInput:
    form = await request.form()
    question_type = QuestionType(str(form.get("question_type")))
    media_url = str(form.get("media_url", "")).strip()
    media_file = form.get("media_file")
    if hasattr(media_file, "filename") and media_file.filename:
        media_url = await _save_uploaded_media(media_file, question_type)
    option_texts = [str(item).strip() for item in form.getlist("option_text") if str(item).strip()]
    match_texts = [str(item).strip() for item in form.getlist("match_text")]
    order_indexes = [str(item).strip() for item in form.getlist("order_index")]
    selected_indexes = {int(index) for index in form.getlist("correct_option") if str(index).isdigit()}
    options = []
    for index, option_text in enumerate(option_texts):
        is_correct = index in selected_indexes or question_type in {
            QuestionType.text_answer,
            QuestionType.free_answer,
            QuestionType.fill_blank,
            QuestionType.code,
            QuestionType.practical,
        }
        if question_type in {QuestionType.fill_blank, QuestionType.code, QuestionType.practical}:
            is_correct = True
        order_index = None
        if index < len(order_indexes) and order_indexes[index].isdigit():
            order_index = int(order_indexes[index])
        options.append(
            OptionInput(
                text=option_text,
                is_correct=is_correct,
                match_text=match_texts[index] if index < len(match_texts) else "",
                order_index=order_index,
            )
        )
    return QuestionInput(
        type=question_type,
        text=str(form.get("text", "")).strip(),
        points=float(form.get("points", 1)),
        options=options,
        media_url=media_url,
        code_language=str(form.get("code_language", "")).strip(),
        code_snippet=str(form.get("code_snippet", "")).strip(),
    )


async def _render_editor(
    request: Request,
    current_user: User,
    test_id: str,
    error: str | None = None,
    status_code: int = 200,
):
    test = await get_manageable_test(test_id, current_user)
    return templates.TemplateResponse(
        request=request,
        name=_manager_template(current_user, "test_edit"),
        context={
            "current_user": current_user,
            "test": test,
            "test_links": await list_test_links(test, current_user),
            "assignments": await list_test_assignments(test, current_user),
            "groups": await list_groups(current_user),
            "all_users": await list_users(),
            "question_types": list(QuestionType),
            "error": error,
        },
        status_code=status_code,
    )


@router.get("/manage")
async def manage_tests_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    return templates.TemplateResponse(
        request=request,
        name=_manager_template(current_user, "tests"),
        context={
            "current_user": current_user,
            "tests": await list_manageable_tests(current_user),
        },
    )


@router.get("/create")
async def create_test_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    return templates.TemplateResponse(
        request=request,
        name=_manager_template(current_user, "test_create"),
        context={"current_user": current_user},
    )


@router.post("/create")
async def create_test_submit(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    title: str = Form(...),
    description: str = Form(""),
    visibility: TestVisibility = Form(TestVisibility.private),
    status: TestStatus = Form(TestStatus.draft),
    time_limit_minutes: str = Form(""),
    max_attempts: int = Form(1),
    passing_score: int = Form(60),
    show_result: bool = Form(False),
    show_correct_answers: bool = Form(False),
    shuffle_questions: bool = Form(False),
    shuffle_answers: bool = Form(False),
    instruction_enabled: bool = Form(False),
    instruction_text: str = Form(""),
    flow_mode: TestFlowMode = Form(TestFlowMode.all_questions),
    allow_question_skip: bool = Form(False),
):
    try:
        payload = _build_test_payload(
            title=title,
            description=description,
            visibility=visibility,
            status=status,
            time_limit_minutes=time_limit_minutes,
            max_attempts=max_attempts,
            passing_score=passing_score,
            show_result=show_result,
            show_correct_answers=show_correct_answers,
            shuffle_questions=shuffle_questions,
            shuffle_answers=shuffle_answers,
            instruction_enabled=instruction_enabled,
            instruction_text=instruction_text,
            flow_mode=flow_mode,
            allow_question_skip=allow_question_skip,
        )
        test = await create_test(current_user, payload)
    except Exception as exc:  # noqa: BLE001
        return templates.TemplateResponse(
            request=request,
            name=_manager_template(current_user, "test_create"),
            context={"current_user": current_user, "error": getattr(exc, "detail", str(exc))},
            status_code=getattr(exc, "status_code", 400),
        )

    return RedirectResponse(url=_edit_redirect_url(test.id, "Тест создан.", "test-settings"), status_code=303)


@router.post("/import")
async def import_test_submit(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    json_file: UploadFile = File(...),
):
    try:
        raw_content = await json_file.read()
        data = json.loads(raw_content.decode("utf-8-sig"))
        payload = TestImport.model_validate(data.get("test", data) if isinstance(data, dict) else data)
        test = await import_test(current_user, payload)
    except json.JSONDecodeError as exc:
        tests = await list_manageable_tests(current_user)
        return templates.TemplateResponse(
            request=request,
            name=_manager_template(current_user, "tests"),
            context={"current_user": current_user, "tests": tests, "error": f"JSON не удалось прочитать: {exc.msg}."},
            status_code=400,
        )
    except ValidationError as exc:
        tests = await list_manageable_tests(current_user)
        return templates.TemplateResponse(
            request=request,
            name=_manager_template(current_user, "tests"),
            context={"current_user": current_user, "tests": tests, "error": _format_validation_error(exc)},
            status_code=400,
        )
    except Exception as exc:  # noqa: BLE001
        tests = await list_manageable_tests(current_user)
        return templates.TemplateResponse(
            request=request,
            name=_manager_template(current_user, "tests"),
            context={"current_user": current_user, "tests": tests, "error": getattr(exc, "detail", str(exc))},
            status_code=getattr(exc, "status_code", 400),
        )

    return RedirectResponse(url=f"/tests/{test.id}/edit", status_code=303)


@router.get("/{test_id}/edit")
async def edit_test_page(
    test_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    return await _render_editor(request, current_user, test_id)


@router.post("/{test_id}/edit")
async def update_test_submit(
    test_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    title: str = Form(...),
    description: str = Form(""),
    visibility: TestVisibility = Form(TestVisibility.private),
    status: TestStatus = Form(TestStatus.draft),
    time_limit_minutes: str = Form(""),
    max_attempts: int = Form(1),
    passing_score: int = Form(60),
    show_result: bool = Form(False),
    show_correct_answers: bool = Form(False),
    shuffle_questions: bool = Form(False),
    shuffle_answers: bool = Form(False),
    instruction_enabled: bool = Form(False),
    instruction_text: str = Form(""),
    flow_mode: TestFlowMode = Form(TestFlowMode.all_questions),
    allow_question_skip: bool = Form(False),
):
    try:
        test = await get_manageable_test(test_id, current_user)
        payload = TestUpdate(**_build_test_payload(
            title=title,
            description=description,
            visibility=visibility,
            status=status,
            time_limit_minutes=time_limit_minutes,
            max_attempts=max_attempts,
            passing_score=passing_score,
            show_result=show_result,
            show_correct_answers=show_correct_answers,
            shuffle_questions=shuffle_questions,
            shuffle_answers=shuffle_answers,
            instruction_enabled=instruction_enabled,
            instruction_text=instruction_text,
            flow_mode=flow_mode,
            allow_question_skip=allow_question_skip,
        ).model_dump())
        await update_test(test, current_user, payload)
    except Exception as exc:  # noqa: BLE001
        return await _render_editor(
            request,
            current_user,
            test_id,
            error=getattr(exc, "detail", str(exc)),
            status_code=getattr(exc, "status_code", 400),
        )

    return RedirectResponse(url=_edit_redirect_url(test_id, "Тест сохранен.", "test-settings"), status_code=303)


@router.post("/{test_id}/questions")
async def add_question_submit(
    test_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    try:
        test = await get_manageable_test(test_id, current_user)
        payload = await _build_question_payload(request)
        await save_question(test, current_user, payload)
    except Exception as exc:  # noqa: BLE001
        return await _render_editor(
            request,
            current_user,
            test_id,
            error=getattr(exc, "detail", str(exc)),
            status_code=getattr(exc, "status_code", 400),
        )

    return RedirectResponse(url=_edit_redirect_url(test_id, "Вопрос добавлен.", "add-question"), status_code=303)


@router.post("/{test_id}/questions/{question_id}")
async def update_question_submit(
    test_id: str,
    question_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    try:
        test = await get_manageable_test(test_id, current_user)
        payload = await _build_question_payload(request)
        await save_question(test, current_user, payload, question_id=question_id)
    except Exception as exc:  # noqa: BLE001
        return await _render_editor(
            request,
            current_user,
            test_id,
            error=getattr(exc, "detail", str(exc)),
            status_code=getattr(exc, "status_code", 400),
        )
    return RedirectResponse(url=_edit_redirect_url(test_id, "Вопрос сохранен.", f"question-{question_id}"), status_code=303)


@router.post("/{test_id}/questions/{question_id}/delete")
async def delete_question_submit(
    test_id: str,
    question_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    test = await get_manageable_test(test_id, current_user)
    await delete_question(test, current_user, question_id)
    return RedirectResponse(url=f"/tests/{test_id}/edit", status_code=303)


@router.post("/{test_id}/delete")
async def delete_test_submit(
    test_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    test = await get_manageable_test(test_id, current_user)
    await delete_test_record(test, current_user)
    return RedirectResponse(url="/tests/manage", status_code=303)


@router.post("/{test_id}/links")
async def create_link_submit(
    test_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    expires_at: str = Form(""),
    max_uses: str = Form(""),
    allowed_group_id: str = Form(""),
    allowed_user_ids: list[str] = Form(default=[]),
):
    from datetime import datetime
    from datetime import timezone

    try:
        test = await get_manageable_test(test_id, current_user)
        expires_at_value = None
        if expires_at:
            parsed_dt = datetime.fromisoformat(expires_at)
            expires_at_value = parsed_dt if parsed_dt.tzinfo else parsed_dt.replace(tzinfo=timezone.utc)
        payload = TestLinkCreate(
            expires_at=expires_at_value,
            max_uses=int(max_uses) if max_uses else None,
            allowed_group_id=allowed_group_id or None,
            allowed_user_ids=allowed_user_ids,
        )
        await create_private_link(test, current_user, payload)
    except Exception as exc:  # noqa: BLE001
        return await _render_editor(
            request,
            current_user,
            test_id,
            error=getattr(exc, "detail", str(exc)),
            status_code=getattr(exc, "status_code", 400),
        )

    return RedirectResponse(url=f"/tests/{test_id}/edit", status_code=303)


@router.post("/{test_id}/assignments")
async def create_assignment_submit(
    test_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
    group_id: str = Form(...),
):
    try:
        test = await get_manageable_test(test_id, current_user)
        assignment = await create_test_assignment(test, current_user, group_id)
    except Exception as exc:  # noqa: BLE001
        return await _render_editor(
            request,
            current_user,
            test_id,
            error=getattr(exc, "detail", str(exc)),
            status_code=getattr(exc, "status_code", 400),
        )

    return RedirectResponse(url=f"/tests/assignments/{assignment.id}/monitor", status_code=303)


@router.get("/assignments/{assignment_id}/monitor")
async def assignment_monitor_page(
    assignment_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    assignment, test, group = await get_assignment_for_management(assignment_id, current_user)
    members = await User.find({"_id": {"$in": group.members}}).to_list() if group.members else []
    attempts_by_user = await latest_attempts_by_assignment(assignment.id, group.members)
    return templates.TemplateResponse(
        request=request,
        name="examiner/assignment_monitor.html",
        context={
            "current_user": current_user,
            "assignment": assignment,
            "test": test,
            "group": group,
            "members": members,
            "attempts_by_user": attempts_by_user,
        },
    )


@router.post("/assignments/{assignment_id}/finish")
async def finish_assignment_for_group_submit(
    assignment_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    assignment, _, group = await get_assignment_for_management(assignment_id, current_user)
    attempts_by_user = await latest_attempts_by_assignment(assignment.id, group.members)
    for attempt in attempts_by_user.values():
        await terminate_attempt(attempt, current_user)
    await close_assignment_for_group(assignment, current_user)
    return RedirectResponse(url=f"/tests/assignments/{assignment_id}/monitor", status_code=303)


@router.post("/assignments/{assignment_id}/members/{member_id}/finish")
async def finish_assignment_for_member_submit(
    assignment_id: str,
    member_id: str,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.examiner)),
):
    assignment, _, _ = await get_assignment_for_management(assignment_id, current_user)
    attempts_by_user = await latest_attempts_by_assignment(assignment.id, [member_id])
    attempt = attempts_by_user.get(member_id)
    if attempt:
        await terminate_attempt(attempt, current_user)
    await close_assignment_for_user(assignment, current_user, member_id)
    await close_assignment_if_all_members_done(assignment.id)
    return RedirectResponse(url=f"/tests/assignments/{assignment_id}/monitor", status_code=303)


@router.get("/catalog")
async def public_catalog_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    return templates.TemplateResponse(
        request=request,
        name="student/catalog.html",
        context={
            "current_user": current_user,
            "tests": await list_public_tests(),
        },
    )


@router.get("/assigned")
async def assigned_tests_page(
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    assignments = await list_assignments_for_student(current_user)
    tests = await Test.find({"_id": {"$in": [assignment.test_id for assignment in assignments]}}).to_list() if assignments else []
    tests_by_id = {test.id: test for test in tests}
    return templates.TemplateResponse(
        request=request,
        name="student/assigned_tests.html",
        context={
            "current_user": current_user,
            "assignments": assignments,
            "tests_by_id": tests_by_id,
        },
    )


@router.get("/assignments/{assignment_id}/take")
async def take_assigned_test_page(
    assignment_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    assignment, test, _ = await get_assignment_for_student(assignment_id, current_user)
    attempt = await get_or_create_attempt(test, current_user, assignment=assignment)
    if attempt.status not in {AttemptStatus.started, AttemptStatus.revision_requested}:
        return RedirectResponse(url=f"/attempts/{attempt.id}", status_code=303)
    remaining_seconds = None if attempt.status == AttemptStatus.revision_requested else _remaining_seconds(attempt)
    return templates.TemplateResponse(
        request=request,
        name="student/take_test.html",
        context={
            "current_user": current_user,
            "test": test,
            "attempt": attempt,
            "visible_answers": _visible_answers_for_take(attempt),
            "is_revision": attempt.status == AttemptStatus.revision_requested,
            "remaining_seconds": remaining_seconds,
        },
    )


@router.get("/{test_id}/take")
async def take_public_test_page(
    test_id: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    test = await get_public_test_for_student(test_id)
    attempt = await get_or_create_attempt(test, current_user)
    if attempt.status not in {AttemptStatus.started, AttemptStatus.revision_requested}:
        return RedirectResponse(url=f"/attempts/{attempt.id}", status_code=303)
    remaining_seconds = None if attempt.status == AttemptStatus.revision_requested else _remaining_seconds(attempt)
    return templates.TemplateResponse(
        request=request,
        name="student/take_test.html",
        context={
            "current_user": current_user,
            "test": test,
            "attempt": attempt,
            "visible_answers": _visible_answers_for_take(attempt),
            "is_revision": attempt.status == AttemptStatus.revision_requested,
            "remaining_seconds": remaining_seconds,
        },
    )


@router.get("/link/{token}")
async def take_private_test_page(
    token: str,
    request: Request,
    current_user: User = Depends(require_roles(UserRole.student)),
):
    link, test = await validate_test_link(token, current_user)
    attempt = await get_or_create_attempt(test, current_user, link)
    if attempt.status not in {AttemptStatus.started, AttemptStatus.revision_requested}:
        return RedirectResponse(url=f"/attempts/{attempt.id}", status_code=303)
    remaining_seconds = None if attempt.status == AttemptStatus.revision_requested else _remaining_seconds(attempt)
    return templates.TemplateResponse(
        request=request,
        name="student/take_test.html",
        context={
            "current_user": current_user,
            "test": test,
            "attempt": attempt,
            "visible_answers": _visible_answers_for_take(attempt),
            "is_revision": attempt.status == AttemptStatus.revision_requested,
            "private_token": token,
            "remaining_seconds": remaining_seconds,
        },
    )
