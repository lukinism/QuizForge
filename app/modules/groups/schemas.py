from pydantic import BaseModel, Field


class GroupCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    members: list[str] = Field(default_factory=list)
