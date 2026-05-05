from datetime import datetime
from enum import Enum
from typing import TypedDict

from pydantic import BaseModel, Field


class SectionPriority(str, Enum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class SectionStatus(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in-review"
    APPROVED = "approved"
    SKIPPED = "skipped"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PUBLISHED = "published"


class TemplateSection(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    priority: SectionPriority
    guidance: str
    suggested_roles: list[str] = Field(default_factory=list)


class Template(BaseModel):
    model_config = {"extra": "ignore"}

    name: str = Field(min_length=1)
    description: str
    ai_context: str
    sections: list[TemplateSection]
    slug: str | None = None


class User(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    email: str
    default_roles: list[str] = Field(default_factory=list)


class UserRegistry(BaseModel):
    users: list[User]


class ParticipantInput(BaseModel):
    user_id: str = Field(min_length=1)
    assigned_sections: list[str] = Field(default_factory=list)
    role: str = "participant"


class Participant(BaseModel):
    user_id: str
    token: str
    assigned_sections: list[str]
    role: str


class SectionMeta(BaseModel):
    filename: str
    status: SectionStatus = SectionStatus.DRAFT


class Session(BaseModel):
    id: str = Field(min_length=1)
    template: str = Field(min_length=1)
    status: SessionStatus = SessionStatus.ACTIVE
    coordinator: str = Field(min_length=1)
    agent_session_id: str | None = None
    participants: list[Participant] = Field(default_factory=list)
    section_meta: dict[str, SectionMeta] = Field(default_factory=dict)
    created_at: datetime
    published_at: datetime | None = None
    output_ref: str | None = None


class Comment(BaseModel):
    id: str
    author: str = Field(min_length=1)
    text: str = Field(min_length=1)
    timestamp: datetime


class Proposal(BaseModel):
    id: str
    section_id: str
    triggered_by_comment: str
    revised_text: str
    summary: str
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: datetime


class SectionContent(TypedDict):
    title: str
    content: str


class ProgressInfo(TypedDict):
    total: int
    approved: int
    skipped: int
    required_remaining: int


class SectionContentResponse(TypedDict):
    section_id: str
    content: str
    status: str
