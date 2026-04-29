from datetime import datetime
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.odm import Document, PydanticObjectId
from app.core.utils import utcnow


class TestVisibility(str, Enum):
    public = "public"
    private = "private"


class TestStatus(str, Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class QuestionType(str, Enum):
    single_choice = "single_choice"
    multiple_choice = "multiple_choice"
    text_answer = "text_answer"
    free_answer = "free_answer"
    matching = "matching"
    ordering = "ordering"
    fill_blank = "fill_blank"
    image = "image"
    audio = "audio"
    video = "video"
    file = "file"
    code = "code"
    practical = "practical"


class TestFlowMode(str, Enum):
    all_questions = "all_questions"
    one_by_one = "one_by_one"


class QuestionOption(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    is_correct: bool = False
    match_text: str = ""
    order_index: int | None = None


class TestSettings(BaseModel):
    time_limit_minutes: int | None = Field(default=None, ge=1, le=240)
    max_attempts: int = Field(default=1, ge=1, le=50)
    passing_score: int = Field(default=60, ge=0, le=100)
    show_result: bool = True
    show_correct_answers: bool = False
    shuffle_questions: bool = False
    shuffle_answers: bool = False
    instruction_enabled: bool = False
    instruction_text: str = ""
    flow_mode: TestFlowMode = TestFlowMode.all_questions
    allow_question_skip: bool = True


class Question(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: QuestionType
    text: str
    points: float = Field(default=1, ge=0)
    options: list[QuestionOption] = Field(default_factory=list)
    media_url: str = ""
    code_language: str = ""
    code_snippet: str = ""


class Test(Document):
    title: str
    description: str = ""
    author_id: PydanticObjectId
    visibility: TestVisibility = TestVisibility.private
    status: TestStatus = TestStatus.draft
    settings: TestSettings = Field(default_factory=TestSettings)
    questions: list[Question] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "tests"
        indexes = ["author_id", "visibility", "status", "created_at"]


class TestLink(Document):
    test_id: PydanticObjectId
    token: str = Field(default_factory=lambda: str(uuid4()))
    is_active: bool = True
    expires_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    used_count: int = Field(default=0, ge=0)
    allowed_group_id: PydanticObjectId | None = None
    allowed_user_ids: list[PydanticObjectId] = Field(default_factory=list)
    created_by: PydanticObjectId
    created_at: datetime = Field(default_factory=utcnow)

    class Settings:
        name = "test_links"
        indexes = ["test_id", "token", "created_by", "expires_at"]


class TestAssignment(Document):
    test_id: PydanticObjectId
    group_id: PydanticObjectId
    created_by: PydanticObjectId
    is_active: bool = True
    closed_user_ids: list[PydanticObjectId] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None

    class Settings:
        name = "test_assignments"
        indexes = ["test_id", "group_id", "created_by", "is_active", "created_at"]
