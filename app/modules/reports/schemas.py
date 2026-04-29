from datetime import date

from pydantic import BaseModel

from app.modules.reports.models import ReportType


class ReportFiltersInput(BaseModel):
    test_id: str | None = None
    group_id: str | None = None
    user_id: str | None = None
    private_link_id: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = None


class ReportOptionsInput(BaseModel):
    include_answers: bool = False
    include_correct_answers: bool = False
    include_statistics: bool = True
    include_charts: bool = False
    include_signature: bool = True
    include_qr: bool = True


class ReportCreateInput(BaseModel):
    report_type: ReportType
    filters: ReportFiltersInput
    options: ReportOptionsInput


REPORT_STATUS_CHOICES = [
    "",
    "started",
    "finished",
    "expired",
    "pending_manual_review",
    "checked",
    "passed",
    "failed",
]
