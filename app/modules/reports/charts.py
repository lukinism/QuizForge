def ratio_bar(label: str, value: int | float, total: int | float, color: str = "#0d6efd") -> dict:
    percent = round((float(value) / float(total)) * 100, 2) if total else 0
    return {"label": label, "value": value, "total": total, "percent": percent, "color": color}


def pass_fail_chart(passed: int, failed: int) -> list[dict]:
    total = passed + failed
    return [
        ratio_bar("Сдали", passed, total, "#198754"),
        ratio_bar("Не сдали", failed, total, "#dc3545"),
    ]


def score_distribution(attempts) -> list[dict]:
    buckets = [
        ("0-20%", 0, 20),
        ("21-40%", 21, 40),
        ("41-60%", 41, 60),
        ("61-80%", 61, 80),
        ("81-100%", 81, 100),
    ]
    rows = []
    total = len(attempts)
    for label, start, end in buckets:
        count = sum(1 for attempt in attempts if start <= attempt.percent <= end)
        rows.append(ratio_bar(label, count, total, "#6f42c1"))
    return rows


def question_error_chart(question_rows: list[dict]) -> list[dict]:
    return [
        ratio_bar(row["question"], row["wrong_count"], row["total_count"], "#fd7e14")
        for row in question_rows[:10]
    ]
