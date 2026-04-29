from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Request

from app.core.config import get_settings
from app.core.security import decode_token
from app.modules.users.models import User


ERROR_MESSAGE_MAP = {
    "Authentication required": "Нужно войти в систему, чтобы продолжить.",
    "Insufficient permissions": "У вас нет прав для доступа к этому разделу.",
    "Access denied": "Доступ к этому разделу запрещен.",
    "User is blocked": "Ваш аккаунт заблокирован.",
    "User is blocked or missing": "Аккаунт заблокирован или больше недоступен.",
    "Refresh token is missing": "Сессия истекла. Войдите в систему снова.",
    "Invalid refresh token": "Сессия истекла. Войдите в систему снова.",
    "Object not found": "Запрошенный объект не найден.",
    "Test not found": "Тест не найден.",
    "Question not found": "Вопрос не найден.",
    "Group not found": "Группа не найдена.",
    "Attempt not found": "Попытка не найдена.",
    "Report not found": "Отчет не найден.",
    "Link not found": "Приватная ссылка не найдена.",
    "Published test not found": "Опубликованный тест не найден.",
    "Link is inactive": "Эта приватная ссылка отключена.",
    "Link has expired": "Срок действия приватной ссылки истек.",
    "Link usage limit reached": "Лимит использований приватной ссылки исчерпан.",
    "User is not allowed for this link": "У вас нет доступа по этой приватной ссылке.",
    "User is not a member of the allowed group": "Вы не входите в разрешенную группу для этого теста.",
    "Test is not publicly available": "Этот тест сейчас недоступен для публичного прохождения.",
    "Attempt limit reached": "Лимит попыток для этого теста уже исчерпан.",
    "Attempt is already completed": "Эта попытка уже завершена.",
    "The test has no questions": "В тесте пока нет вопросов.",
    "Only published tests can be shared by private link": "Приватную ссылку можно создать только для опубликованного теста.",
    "Only students can start attempts from the participant interface": "Прохождение тестов доступно только тестируемым.",
    "Email is already registered": "Пользователь с таким адресом электронной почты уже зарегистрирован.",
    "Username is already taken": "Это имя пользователя уже занято.",
    "Invalid email or password": "Неверный адрес электронной почты или пароль.",
    "Нужно войти в систему, чтобы продолжить.": "Нужно войти в систему, чтобы продолжить.",
    "У вас нет прав для доступа к этому разделу.": "У вас нет прав для доступа к этому разделу.",
    "Доступ к этому разделу запрещен.": "Доступ к этому разделу запрещен.",
    "Ваш аккаунт заблокирован.": "Ваш аккаунт заблокирован.",
    "Аккаунт заблокирован или больше недоступен.": "Аккаунт заблокирован или больше недоступен.",
    "Сессия истекла. Войдите в систему снова.": "Сессия истекла. Войдите в систему снова.",
    "Запрошенный объект не найден.": "Запрошенный объект не найден.",
    "Тест не найден.": "Тест не найден.",
    "Вопрос не найден.": "Вопрос не найден.",
    "Группа не найдена.": "Группа не найдена.",
    "Попытка не найдена.": "Попытка не найдена.",
    "Отчет не найден.": "Отчет не найден.",
    "Приватная ссылка не найдена.": "Приватная ссылка не найдена.",
    "Опубликованный тест не найден.": "Опубликованный тест не найден.",
    "Эта приватная ссылка отключена.": "Эта приватная ссылка отключена.",
    "Срок действия приватной ссылки истек.": "Срок действия приватной ссылки истек.",
    "Лимит использований приватной ссылки исчерпан.": "Лимит использований приватной ссылки исчерпан.",
    "У вас нет доступа по этой приватной ссылке.": "У вас нет доступа по этой приватной ссылке.",
    "Вы не входите в разрешенную группу для этого теста.": "Вы не входите в разрешенную группу для этого теста.",
    "Этот тест сейчас недоступен для публичного прохождения.": "Этот тест сейчас недоступен для публичного прохождения.",
    "Лимит попыток для этого теста уже исчерпан.": "Лимит попыток для этого теста уже исчерпан.",
    "Эта попытка уже завершена.": "Эта попытка уже завершена.",
    "В тесте пока нет вопросов.": "В тесте пока нет вопросов.",
    "Приватную ссылку можно создать только для опубликованного теста.": "Приватную ссылку можно создать только для опубликованного теста.",
    "Прохождение тестов доступно только тестируемым.": "Прохождение тестов доступно только тестируемым.",
    "Вступать в группы могут только тестируемые.": "Вступать в группы могут только тестируемые.",
    "Ссылка для вступления недоступна.": "Ссылка для вступления недоступна.",
    "Вы заблокированы в этой группе.": "Вы заблокированы в этой группе.",
    "Ссылка не найдена.": "Ссылка не найдена.",
    "Выдача этого теста уже завершена.": "Выдача этого теста уже завершена.",
    "Этот тест для вас завершен проверяющим.": "Этот тест для вас завершен проверяющим.",
    "Выдать группе можно только опубликованный тест.": "Выдать группе можно только опубликованный тест.",
    "Выдача теста не найдена.": "Выдача теста не найдена.",
    "Выданный тест недоступен.": "Выданный тест недоступен.",
    "Вы не состоите в группе для этого теста.": "Вы не состоите в группе для этого теста.",
    "Пользователь с таким email уже зарегистрирован.": "Пользователь с таким адресом электронной почты уже зарегистрирован.",
    "Пользователь с таким адресом электронной почты уже зарегистрирован.": "Пользователь с таким адресом электронной почты уже зарегистрирован.",
    "Этот username уже занят.": "Это имя пользователя уже занято.",
    "Это имя пользователя уже занято.": "Это имя пользователя уже занято.",
    "Неверный email или пароль.": "Неверный адрес электронной почты или пароль.",
    "Неверный адрес электронной почты или пароль.": "Неверный адрес электронной почты или пароль.",
    "Пользователь не найден.": "Пользователь не найден.",
    "Администратор не может снять роль admin с самого себя.": "Администратор не может снять с самого себя роль администратора.",
    "Администратор не может снять с самого себя роль администратора.": "Администратор не может снять с самого себя роль администратора.",
    "Администратор не может заблокировать самого себя.": "Администратор не может заблокировать самого себя.",
    "У вопроса с вариантами ответа должно быть минимум два варианта.": "У вопроса с вариантами ответа должно быть минимум два варианта.",
    "Для вопроса с одним выбором нужно указать ровно один правильный ответ.": "Для вопроса с одним выбором нужно указать ровно один правильный ответ.",
    "Для вопроса с множественным выбором нужен хотя бы один правильный ответ.": "Для вопроса с множественным выбором нужен хотя бы один правильный ответ.",
    "Для текстового вопроса нужно указать хотя бы один допустимый правильный ответ.": "Для текстового вопроса нужно указать хотя бы один допустимый правильный ответ.",
}

TOAST_LEVELS = {
    400: "danger",
    401: "warning",
    403: "danger",
    404: "secondary",
    500: "danger",
    503: "warning",
}


def request_prefers_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "application/xhtml+xml" in accept or "*/*" in accept


def humanize_error(detail: object) -> str:
    if isinstance(detail, str):
        return ERROR_MESSAGE_MAP.get(detail, detail)
    return "Произошла ошибка при обработке запроса."


def toast_level_for_status(status_code: int) -> str:
    return TOAST_LEVELS.get(status_code, "danger")


def _append_toast(url: str, message: str, level: str) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["toast"] = message
    query["toast_level"] = level
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _same_origin_url(request: Request, url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.netloc:
        return urlunsplit(("", "", parts.path or "/", parts.query, parts.fragment))

    request_parts = urlsplit(str(request.base_url))
    if parts.netloc != request_parts.netloc:
        return None
    return urlunsplit(("", "", parts.path or "/", parts.query, parts.fragment))


def build_redirect_back_url(
    request: Request,
    message: str,
    level: str,
    fallback: str = "/",
) -> str:
    referer = request.headers.get("referer")
    safe_referer = _same_origin_url(request, referer) if referer else None
    target = safe_referer or fallback
    return _append_toast(target, message, level)


def build_login_redirect_url(request: Request, message: str, level: str) -> str:
    next_path = urlunsplit(("", "", request.url.path, request.url.query, ""))
    target = f"/auth/login?next={urlencode({'next': next_path}).split('=', 1)[1]}"
    return _append_toast(target, message, level)


async def resolve_current_user_from_request(request: Request) -> User | None:
    settings = get_settings()
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        return None

    payload = decode_token(token, expected_type="access")
    user_id = payload.get("sub") if payload else None
    if not user_id:
        return None

    return await User.get(user_id)
