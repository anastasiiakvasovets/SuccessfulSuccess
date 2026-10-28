"""Pydantic request/response models for the meetings API."""

import uuid
from datetime import date, datetime

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from app.ai.agenda import ParsedAgenda
from app.config import settings

MAX_PARTICIPANTS = 50
MAX_AGENDA_ROWS = 50


class ParticipantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class ParticipantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str | None
    position: int


class MeetingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=200)
    starts_at: datetime
    ends_at: datetime
    participants: list[ParticipantCreate] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("description", "location")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _require_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("must include a UTC offset, e.g. 2026-09-10T10:00:00+03:00")
        return value

    @field_validator("ends_at")
    @classmethod
    def _after_start(cls, value: datetime, info: ValidationInfo) -> datetime:
        starts_at = info.data.get("starts_at")
        if starts_at is not None and value <= starts_at:
            raise ValueError("must be later than starts_at")
        return value

    @field_validator("participants")
    @classmethod
    def _unique_and_bounded(cls, value: list[ParticipantCreate]) -> list[ParticipantCreate]:
        if len(value) > MAX_PARTICIPANTS:
            raise ValueError(f"a meeting may have at most {MAX_PARTICIPANTS} participants")
        seen: set[tuple[str, str | None]] = set()
        for participant in value:
            key = (participant.name.casefold(), (participant.email or "").casefold() or None)
            if key in seen:
                raise ValueError(f"duplicate participant: {participant.name}")
            seen.add(key)
        return value


class AgendaItem(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    owner: str | None = Field(default=None, max_length=200)
    minutes: int | None = Field(default=None, ge=1, le=480)

    @field_validator("topic")
    @classmethod
    def _strip_topic(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("owner")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class ActionItem(BaseModel):
    task: str = Field(min_length=1, max_length=500)
    owner: str | None = Field(default=None, max_length=200)
    due: date | None = None

    @field_validator("task")
    @classmethod
    def _strip_task(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("owner")
    @classmethod
    def _empty_to_none(cls, value: str | None) -> str | None:
        return (value.strip() or None) if value is not None else None


class Agenda(BaseModel):
    """A meeting's agenda, as saved and as read back."""

    items: list[AgendaItem] = Field(default_factory=list, max_length=MAX_AGENDA_ROWS)
    action_items: list[ActionItem] = Field(default_factory=list, max_length=MAX_AGENDA_ROWS)


class AgendaWrite(Agenda):
    """Saving an agenda, typed by hand or corrected from the parser's suggestion.

    When it started from a suggestion, the browser sends that suggestion
    unchanged, with the model and prompt version that produced it.
    """

    ai_suggestion: ParsedAgenda | None = None
    ai_model: str | None = Field(default=None, max_length=100)
    ai_prompt_version: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _suggestion_is_attributed(self) -> "AgendaWrite":
        if self.ai_suggestion is not None and not (self.ai_model and self.ai_prompt_version):
            raise ValueError("ai_suggestion needs ai_model and ai_prompt_version")
        return self


class MeetingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime
    participants: list[ParticipantRead]
    agenda: Agenda | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("starts_at", "ends_at", "created_at", "updated_at")
    def _in_app_timezone(self, value: datetime) -> str:
        """Render every timestamp with the application timezone's offset.

        Postgres hands back UTC; converting here means all clients read the same
        wall-clock time as the day window the meeting was listed under.
        """
        return value.astimezone(settings.tz).isoformat()


class MeetingList(BaseModel):
    items: list[MeetingRead]
    total: int
    limit: int
    offset: int
    date: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str | None
    email_verified: bool
    name: str | None
    given_name: str | None
    family_name: str | None
    picture_url: str | None
    auth_provider: str
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None


class UserSync(BaseModel):
    id_token: str = Field(min_length=1, description="The Cognito ID token from the same sign-in")
