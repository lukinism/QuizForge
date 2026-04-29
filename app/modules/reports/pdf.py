import textwrap
from pathlib import Path

from app.core.localization import datetime_label

PAGE_SIZE = (1240, 1754)
PAGE_MARGIN = 70
CONTENT_WIDTH = PAGE_SIZE[0] - PAGE_MARGIN * 2
ROW_PADDING = 10
FOOTER_Y = PAGE_SIZE[1] - 48


def _find_font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf" if bold else "C:/Windows/Fonts/calibri.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/local/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/local/share/fonts/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _safe_text(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _person_name(user) -> str:
    if not user:
        return ""
    return user.full_name or user.username


def _date(value, fmt: str = "%d.%m.%Y %H:%M") -> str:
    if not value:
        return ""
    if fmt == "%d.%m.%Y %H:%M":
        return datetime_label(value)
    return value.strftime(fmt)


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(_safe_text(text), width=width, break_long_words=True) or [""]


class PdfCanvas:
    def __init__(self, report_number: str):
        from PIL import Image, ImageDraw

        self.Image = Image
        self.pages = []
        self.report_number = report_number
        self.title_font = _find_font(30, bold=True)
        self.h2_font = _find_font(21, bold=True)
        self.header_font = _find_font(16, bold=True)
        self.text_font = _find_font(15)
        self.small_font = _find_font(12)
        self.new_page()

    def new_page(self) -> None:
        from PIL import ImageDraw

        self.image = self.Image.new("RGB", PAGE_SIZE, "white")
        self.draw = ImageDraw.Draw(self.image)
        self.y = PAGE_MARGIN

    def finish_page(self) -> None:
        self.draw.line((PAGE_MARGIN, FOOTER_Y - 10, PAGE_SIZE[0] - PAGE_MARGIN, FOOTER_Y - 10), fill="#dee2e6", width=1)
        self.draw.text((PAGE_MARGIN, FOOTER_Y), self.report_number, fill="#6c757d", font=self.small_font)
        self.pages.append(self.image)

    def ensure_space(self, height: int) -> None:
        if self.y + height < FOOTER_Y - 20:
            return
        self.finish_page()
        self.new_page()

    def text(self, text: str, x: int, y: int, font=None, fill="#212529") -> None:
        self.draw.text((x, y), _safe_text(text), fill=fill, font=font or self.text_font)

    def wrapped_text(self, text: str, x: int, y: int, width_chars: int, font=None, fill="#212529", line_height: int = 22) -> int:
        lines = _wrap(text, width_chars)
        for line in lines:
            self.text(line, x, y, font=font, fill=fill)
            y += line_height
        return max(len(lines) * line_height, line_height)

    def section(self, title: str) -> None:
        self.ensure_space(48)
        self.y += 12
        self.text(title, PAGE_MARGIN, self.y, self.h2_font, "#0d3b66")
        self.y += 30
        self.draw.line((PAGE_MARGIN, self.y, PAGE_SIZE[0] - PAGE_MARGIN, self.y), fill="#b6c2cf", width=2)
        self.y += 12

    def header(self, title: str, subtitle: str, qr_data_uri: str | None = None) -> None:
        self.text(title, PAGE_MARGIN, self.y, self.title_font, "#0d3b66")
        self.y += 42
        self.text(subtitle, PAGE_MARGIN, self.y, self.text_font, "#495057")
        if qr_data_uri:
            self._draw_qr(qr_data_uri)
        self.y += 38

    def _draw_qr(self, data_uri: str) -> None:
        import base64
        from io import BytesIO

        try:
            from PIL import Image

            encoded = data_uri.split(",", 1)[1]
            qr = Image.open(BytesIO(base64.b64decode(encoded))).resize((110, 110))
            x = PAGE_SIZE[0] - PAGE_MARGIN - 110
            self.image.paste(qr.convert("RGB"), (x, PAGE_MARGIN))
            self.text("Проверка", x + 18, PAGE_MARGIN + 116, self.small_font, "#6c757d")
        except Exception:
            return

    def key_value_table(self, rows: list[tuple[str, str]], columns: int = 2) -> None:
        if not rows:
            return
        label_w = 170
        value_w = (CONTENT_WIDTH // columns) - label_w
        for start in range(0, len(rows), columns):
            chunk = rows[start:start + columns]
            label_chars = max(label_w // 9, 8)
            value_chars = max(value_w // 9, 8)
            cell_heights = []
            for label, value in chunk:
                label_height = max(len(_wrap(label, label_chars)), 1) * 18 + ROW_PADDING * 2
                value_height = max(len(_wrap(value, value_chars)), 1) * 18 + ROW_PADDING * 2
                cell_heights.append(max(label_height, value_height, 46))
            row_h = max(cell_heights)
            self.ensure_space(row_h)
            x = PAGE_MARGIN
            for label, value in chunk:
                self.draw.rectangle((x, self.y, x + label_w, self.y + row_h), fill="#f1f5f9", outline="#cbd5e1")
                self.draw.rectangle((x + label_w, self.y, x + label_w + value_w, self.y + row_h), fill="white", outline="#cbd5e1")
                self.wrapped_text(label, x + ROW_PADDING, self.y + 12, label_chars, self.header_font, "#334155", 18)
                self.wrapped_text(value, x + label_w + ROW_PADDING, self.y + 12, value_chars, self.text_font, "#111827", 18)
                x += label_w + value_w
            self.y += row_h
        self.y += 10

    def stats_grid(self, stats: dict) -> None:
        items = [
            ("Попыток", stats.get("attempts_count", 0)),
            ("Завершено", stats.get("finished_count", 0)),
            ("Начато", stats.get("started_count", 0)),
            ("Сдали", stats.get("passed_count", 0)),
            ("Не сдали", stats.get("failed_count", 0)),
            ("Средний балл", stats.get("average_score", 0)),
            ("Средний %", f"{stats.get('average_percent', 0)}%"),
            ("Успешность", f"{stats.get('success_rate', 0)}%"),
        ]
        cols = 4
        card_w = CONTENT_WIDTH // cols
        card_h = 72
        for start in range(0, len(items), cols):
            self.ensure_space(card_h + 8)
            x = PAGE_MARGIN
            for label, value in items[start:start + cols]:
                self.draw.rounded_rectangle((x, self.y, x + card_w - 8, self.y + card_h), radius=8, fill="#f8fafc", outline="#cbd5e1")
                self.text(str(value), x + 14, self.y + 12, self.h2_font, "#0d3b66")
                self.text(label, x + 14, self.y + 43, self.small_font, "#64748b")
                x += card_w
            self.y += card_h + 8
        self.y += 8

    def table(self, headers: list[str], rows: list[list[str]], widths: list[int], max_rows: int = 90) -> None:
        row_h = 42
        rows = rows[:max_rows]
        self.ensure_space(row_h * 2)
        self._table_header(headers, widths, row_h)
        for index, row in enumerate(rows):
            cells = [_safe_text(cell) for cell in row]
            heights = []
            for cell, width in zip(cells, widths):
                heights.append(max(len(_wrap(cell, max(width // 9, 8))), 1) * 20 + ROW_PADDING * 2)
            height = max(row_h, max(heights))
            self.ensure_space(height + row_h)
            if self.y < PAGE_MARGIN + 5:
                self._table_header(headers, widths, row_h)
            fill = "#ffffff" if index % 2 == 0 else "#f8fafc"
            x = PAGE_MARGIN
            for cell, width in zip(cells, widths):
                self.draw.rectangle((x, self.y, x + width, self.y + height), fill=fill, outline="#d6dee8")
                self.wrapped_text(cell, x + ROW_PADDING, self.y + ROW_PADDING, max(width // 9, 8), self.text_font, line_height=20)
                x += width
            self.y += height
        if not rows:
            self.ensure_space(row_h)
            self.draw.rectangle((PAGE_MARGIN, self.y, PAGE_MARGIN + sum(widths), self.y + row_h), fill="#ffffff", outline="#d6dee8")
            self.text("Нет данных для отображения", PAGE_MARGIN + ROW_PADDING, self.y + 12, self.text_font, "#6c757d")
            self.y += row_h
        self.y += 12

    def _table_header(self, headers: list[str], widths: list[int], row_h: int) -> None:
        x = PAGE_MARGIN
        for header, width in zip(headers, widths):
            self.draw.rectangle((x, self.y, x + width, self.y + row_h), fill="#0d3b66", outline="#0d3b66")
            self.wrapped_text(header, x + ROW_PADDING, self.y + 11, max(width // 9, 8), self.header_font, "white", 18)
            x += width
        self.y += row_h

    def bar_chart(self, rows: list[dict]) -> None:
        if not rows:
            return
        for row in rows[:8]:
            self.ensure_space(50)
            label = f"{row['label']} - {row['percent']}%"
            self.text(label, PAGE_MARGIN, self.y, self.text_font, "#334155")
            self.y += 22
            self.draw.rounded_rectangle((PAGE_MARGIN, self.y, PAGE_MARGIN + CONTENT_WIDTH, self.y + 16), radius=6, fill="#e9ecef")
            bar_w = int(CONTENT_WIDTH * min(float(row["percent"]), 100) / 100)
            self.draw.rounded_rectangle((PAGE_MARGIN, self.y, PAGE_MARGIN + bar_w, self.y + 16), radius=6, fill=row.get("color", "#0d6efd"))
            self.y += 28

    def save(self, output_path: Path) -> None:
        self.finish_page()
        first, *rest = self.pages
        first.save(output_path, "PDF", resolution=150.0, save_all=True, append_images=rest)


def _filter_rows(context: dict) -> list[tuple[str, str]]:
    filters = context.get("filters") or {}
    rows = []
    if filters.get("date_from") or filters.get("date_to"):
        rows.append(("Период", f"{filters.get('date_from', '...')} - {filters.get('date_to', '...')}"))
    if filters.get("status"):
        rows.append(("Статус", filters["status"]))
    if context.get("test"):
        rows.append(("Тест", context["test"].title))
    if context.get("participant"):
        rows.append(("Пользователь", _person_name(context["participant"])))
    if context.get("group"):
        rows.append(("Группа", context["group"].title))
    if context.get("link"):
        rows.append(("Приватная ссылка", context.get("masked_token", "выбрана")))
    return rows


def _draw_common(canvas: PdfCanvas, context: dict) -> None:
    generated_by = context.get("generated_by")
    subtitle = f"Номер {context.get('report_number', '')} · { _date(context.get('created_at')) } · {_person_name(generated_by)}"
    canvas.header(context.get("title", "Отчет"), subtitle, context.get("qr_data_uri"))
    filters = _filter_rows(context)
    if filters:
        canvas.section("Параметры отчета")
        canvas.key_value_table(filters)


def _draw_stats(canvas: PdfCanvas, context: dict) -> None:
    if (context.get("options") or {}).get("include_statistics") and context.get("stats"):
        canvas.section("Статистика")
        canvas.stats_grid(context["stats"])


def _draw_charts(canvas: PdfCanvas, context: dict) -> None:
    if not (context.get("options") or {}).get("include_charts"):
        return
    charts = context.get("charts") or {}
    if not charts:
        return
    canvas.section("Диаграммы")
    for title, rows in charts.items():
        canvas.text(_chart_title(title), PAGE_MARGIN, canvas.y, canvas.header_font, "#334155")
        canvas.y += 26
        canvas.bar_chart(rows)


def _chart_title(value: str) -> str:
    return {
        "pass_fail": "Сдали / не сдали",
        "score_distribution": "Распределение результатов",
        "question_errors": "Ошибки по вопросам",
    }.get(value, value)


def _draw_test(canvas: PdfCanvas, context: dict) -> None:
    test = context["test"]
    author = context.get("author")
    canvas.section("Информация о тесте")
    canvas.key_value_table(
        [
            ("Название", test.title),
            ("Автор", _person_name(author)),
            ("Вопросов", str(len(test.questions))),
            ("Проходной балл", f"{test.settings.passing_score}%"),
            ("Максимальный балл", str(context.get("max_score", ""))),
            ("Создан", _date(test.created_at, "%d.%m.%Y")),
        ]
    )
    if test.description:
        canvas.key_value_table([("Описание", test.description)], columns=1)
    _draw_stats(canvas, context)
    _draw_charts(canvas, context)
    attempts = context.get("attempts") or []
    users = context.get("users") or {}
    rows = []
    for index, attempt in enumerate(attempts, 1):
        user = users.get(attempt.user_id)
        rows.append([str(index), _person_name(user), user.email if user else "", _date(attempt.started_at), f"{attempt.score}/{attempt.max_score}", f"{attempt.percent}%", attempt.status.value])
    canvas.section("Участники")
    canvas.table(["№", "Пользователь", "Email", "Дата", "Баллы", "%", "Статус"], rows, [45, 210, 250, 160, 110, 80, 130])


def _draw_user(canvas: PdfCanvas, context: dict) -> None:
    participant = context["participant"]
    groups = ", ".join(group.title for group in context.get("groups", [])) or "Не указана"
    canvas.section("Пользователь")
    canvas.key_value_table([("Имя", _person_name(participant)), ("Email", participant.email), ("Группа", groups)], columns=1)
    _draw_stats(canvas, context)
    _draw_charts(canvas, context)
    rows = []
    tests = context.get("tests") or {}
    for attempt in context.get("attempts") or []:
        test = tests.get(attempt.test_id)
        rows.append([test.title if test else attempt.test_title, _date(attempt.started_at), f"{attempt.score}/{attempt.max_score}", f"{attempt.percent}%", "Сдан" if attempt.is_passed else attempt.status.value])
    canvas.section("Тесты")
    canvas.table(["Тест", "Дата", "Баллы", "%", "Статус"], rows, [380, 180, 140, 90, 160])
    if (context.get("options") or {}).get("include_answers"):
        _draw_answers(canvas, context)


def _draw_answers(canvas: PdfCanvas, context: dict) -> None:
    canvas.section("Ответы")
    rows = []
    show_correct = (context.get("options") or {}).get("include_correct_answers") and context.get("can_show_correct_answers")
    for attempt in context.get("attempts") or []:
        for answer in attempt.answers:
            user_answer = answer.text_answer or ", ".join(
                option.text for option in answer.options if option.id in answer.selected_options
            )
            correct = ", ".join(option.text for option in answer.options if option.is_correct) if show_correct else ""
            rows.append([answer.question_text, user_answer, correct, f"{answer.points_received}/{answer.max_points}"])
    headers = ["Вопрос", "Ответ", "Правильный ответ", "Баллы"] if show_correct else ["Вопрос", "Ответ", "", "Баллы"]
    canvas.table(headers, rows, [390, 300, 300, 90], max_rows=70)


def _draw_group(canvas: PdfCanvas, context: dict) -> None:
    group = context["group"]
    users = context.get("users") or []
    canvas.section("Группа")
    canvas.key_value_table([("Название", group.title), ("Участников", str(len(users)))])
    _draw_stats(canvas, context)
    _draw_charts(canvas, context)
    attempts_by_user = context.get("attempts_by_user") or {}
    rows = []
    for index, user in enumerate(users, 1):
        attempt = attempts_by_user.get(user.id)
        rows.append([str(index), _person_name(user), user.email, _date(attempt.started_at) if attempt else "Не начинал", f"{attempt.score}/{attempt.max_score}" if attempt else "-", f"{attempt.percent}%" if attempt else "-", attempt.status.value if attempt else "not_started"])
    canvas.section("Участники")
    canvas.table(["№", "Пользователь", "Email", "Дата", "Баллы", "%", "Статус"], rows, [45, 210, 250, 160, 110, 80, 130])
    canvas.section("Итоги по участникам")
    canvas.key_value_table(
        [
            ("Сдали", ", ".join(user.username for user in context.get("passed_users", [])) or "Нет"),
            ("Не сдали", ", ".join(user.username for user in context.get("failed_users", [])) or "Нет"),
            ("Не начали", ", ".join(user.username for user in context.get("not_started_users", [])) or "Нет"),
        ],
        columns=1,
    )


def _draw_date(canvas: PdfCanvas, context: dict) -> None:
    _draw_stats(canvas, context)
    _draw_charts(canvas, context)
    users = context.get("users") or {}
    tests = context.get("tests") or {}
    groups = context.get("groups") or {}
    rows = []
    for attempt in context.get("attempts") or []:
        user = users.get(attempt.user_id)
        test = tests.get(attempt.test_id)
        group_names = ", ".join(group.title for group in groups.get(attempt.user_id, []))
        rows.append([_date(attempt.started_at), _person_name(user), test.title if test else attempt.test_title, group_names, f"{attempt.score}/{attempt.max_score}", f"{attempt.percent}%", attempt.status.value])
    canvas.section("Попытки за период")
    canvas.table(["Дата", "Пользователь", "Тест", "Группа", "Баллы", "%", "Статус"], rows, [160, 180, 250, 160, 100, 70, 110])


def _draw_private_link(canvas: PdfCanvas, context: dict) -> None:
    link = context["link"]
    test = context.get("test")
    creator = context.get("creator")
    canvas.section("Приватная ссылка")
    canvas.key_value_table(
        [
            ("Тест", test.title if test else ""),
            ("Токен", context.get("masked_token", "")),
            ("Создал", _person_name(creator)),
            ("Дата создания", _date(link.created_at)),
            ("Срок действия", _date(link.expires_at) or "Без срока"),
            ("Использований", f"{link.used_count} / {link.max_uses or 'без лимита'}"),
        ]
    )
    _draw_stats(canvas, context)
    _draw_charts(canvas, context)
    users = context.get("users") or {}
    rows = []
    for attempt in context.get("attempts") or []:
        user = users.get(attempt.user_id)
        rows.append([_person_name(user), user.email if user else "", _date(attempt.started_at), f"{attempt.score}/{attempt.max_score}", f"{attempt.percent}%", attempt.status.value])
    canvas.section("Прохождения")
    canvas.table(["Пользователь", "Email", "Дата", "Результат", "%", "Статус"], rows, [220, 260, 170, 120, 80, 130])


def _draw_errors(canvas: PdfCanvas, context: dict) -> None:
    test = context["test"]
    canvas.section("Тест")
    canvas.key_value_table([("Название", test.title), ("Вопросов", str(len(test.questions))), ("Прохождений", str(len(context.get("attempts") or [])))])
    _draw_stats(canvas, context)
    _draw_charts(canvas, context)
    hardest = context.get("hardest_questions") or []
    if hardest:
        canvas.section("Топ-5 сложных вопросов")
        rows = [[row["question"], f"{row['error_percent']}%", str(row["wrong_count"])] for row in hardest]
        canvas.table(["Вопрос", "% ошибок", "Ошибок"], rows, [760, 130, 110], max_rows=5)
    rows = [[row["question"], str(row["total_count"]), str(row["correct_count"]), str(row["wrong_count"]), f"{row['error_percent']}%"] for row in context.get("question_rows") or []]
    canvas.section("Статистика по вопросам")
    canvas.table(["Вопрос", "Всего", "Верно", "Ошибки", "% ошибок"], rows, [620, 90, 90, 90, 120])


def _draw_signature(canvas: PdfCanvas, context: dict) -> None:
    if not (context.get("options") or {}).get("include_signature"):
        return
    canvas.section("Подпись")
    canvas.key_value_table(
        [
            ("Сформировано", "Системой онлайн-тестирования"),
            ("Дата", _date(context.get("created_at"))),
            ("Ответственный", _person_name(context.get("generated_by"))),
            ("Подпись", "______________________"),
        ]
    )


def _write_pillow_pdf(template_name: str, context: dict, output_path: Path) -> None:
    try:
        import PIL.Image
        import PIL.ImageDraw
    except ImportError as exc:
        raise RuntimeError("Генерация PDF недоступна: не установлен Pillow.") from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = PdfCanvas(context.get("report_number", ""))
    _draw_common(canvas, context)
    if "errors" in template_name:
        _draw_errors(canvas, context)
    elif "private_link" in template_name:
        _draw_private_link(canvas, context)
    elif "date" in template_name:
        _draw_date(canvas, context)
    elif "group" in template_name:
        _draw_group(canvas, context)
    elif "user" in template_name:
        _draw_user(canvas, context)
    else:
        _draw_test(canvas, context)
    _draw_signature(canvas, context)
    canvas.save(output_path)


def write_pdf(template_name: str, context: dict, output_path: Path) -> None:
    _write_pillow_pdf(template_name, context, output_path)
