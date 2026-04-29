from pydantic import BaseModel, Field


class AttemptSubmitAnswer(BaseModel):
    question_id: str
    selected_options: list[str] = Field(default_factory=list)
    text_answer: str | None = None


class AttemptSubmit(BaseModel):
    answers: list[AttemptSubmitAnswer] = Field(default_factory=list)
