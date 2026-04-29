from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.tests.models import QuestionType, TestSettings, TestStatus, TestVisibility


class OptionInput(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    is_correct: bool = False
    match_text: str = Field(default="", max_length=500)
    order_index: int | None = Field(default=None, ge=1)


class QuestionInput(BaseModel):
    type: QuestionType
    text: str = Field(min_length=1, max_length=3000)
    points: float = Field(default=1, ge=0)
    options: list[OptionInput] = Field(default_factory=list)
    media_url: str = Field(default="", max_length=1000)
    code_language: str = Field(default="", max_length=80)
    code_snippet: str = Field(default="", max_length=10000)


class TestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    visibility: TestVisibility = TestVisibility.private
    status: TestStatus = TestStatus.draft
    settings: TestSettings = Field(default_factory=TestSettings)


class TestUpdate(TestCreate):
    pass


class TestImport(TestCreate):
    questions: list[QuestionInput] = Field(default_factory=list)


class TestLinkCreate(BaseModel):
    expires_at: datetime | None = None
    max_uses: int | None = Field(default=None, ge=1)
    allowed_group_id: str | None = None
    allowed_user_ids: list[str] = Field(default_factory=list)
