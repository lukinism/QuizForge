from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.core.odm import Document, PydanticObjectId
from app.core.utils import utcnow
from app.modules.tests.models import QuestionType


class AttemptStatus(str, Enum):
    started = "started"
    pending_review = "pending_review"
    revision_requested = "revision_requested"
    finished = "finished"
    expired = "expired"
    terminated = "terminated"


class AttemptOptionSnapshot(BaseModel):
    id: str
    text: str
    is_correct: bool = False
    match_text: str = ""
    order_index: int | None = None


class AttemptAnswer(BaseModel):
    question_id: str
    question_text: str
    question_type: QuestionType
    selected_options: list[str] = Field(default_factory=list)
    text_answer: str | None = None
    is_correct: bool | None = None
    points_received: float = 0
    max_points: float = 0
    options: list[AttemptOptionSnapshot] = Field(default_factory=list)
    media_url: str = ""
    code_language: str = ""
    code_snippet: str = ""
    requires_manual_review: bool = False
    manual_reviewed: bool = False
    review_comment: str = ""


class Attempt(Document):
    test_id: PydanticObjectId
    test_title: str
    user_id: PydanticObjectId
    test_link_id: PydanticObjectId | None = None
    assignment_id: PydanticObjectId | None = None
    time_limit_minutes: int | None = None
    show_result: bool = True
    show_correct_answers: bool = False
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    status: AttemptStatus = AttemptStatus.started
    score: float = 0
    max_score: float = 0
    percent: float = 0
    is_passed: bool = False
    passing_score: int = 60
    answers: list[AttemptAnswer] = Field(default_factory=list)

    class Settings:
        name = "attempts"
        indexes = ["test_id", "user_id", "assignment_id", "status", "started_at"]
