from __future__ import annotations

from datetime import datetime
from enum import Enum


ENUM_LABELS = {
    "admin": "Администратор",
    "examiner": "Проверяющий",
    "student": "Тестируемый",
    "public": "Публичный",
    "private": "Приватный",
    "draft": "Черновик",
    "published": "Опубликован",
    "archived": "В архиве",
    "started": "Начата",
    "pending_review": "Требует проверки",
    "revision_requested": "Отправлена на доработку",
    "finished": "Завершена",
    "expired": "Просрочена",
    "terminated": "Завершена досрочно",
    "not_started": "Не начато",
    "single_choice": "Один вариант",
    "multiple_choice": "Несколько вариантов",
    "text_answer": "Краткий ответ",
    "free_answer": "Развернутый ответ",
    "matching": "Соответствие",
    "ordering": "Сортировка по порядку",
    "fill_blank": "Заполнение пропусков",
    "image": "Вопрос с изображением",
    "audio": "Вопрос с аудио",
    "video": "Вопрос с видео",
    "file": "Вопрос с файлом",
    "code": "Вопрос с кодом",
    "practical": "Практическое задание",
    "all_questions": "Все вопросы сразу",
    "one_by_one": "По одному вопросу",
    "user_result": "По пользователю",
    "group_result": "По группе",
    "test_result": "По тесту",
}


def enum_label(value: Enum | str | None) -> str:
    if value is None:
        return ""

    raw_value = value.value if isinstance(value, Enum) else str(value)
    return ENUM_LABELS.get(raw_value, raw_value.replace("_", " ").strip())


MONTH_NAMES = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}


def datetime_label(value: datetime | None) -> str:
    if not value:
        return ""
    month = MONTH_NAMES.get(value.month, "")
    return f"{value.day} {month} {value.year}г в {value:%H:%M}"
