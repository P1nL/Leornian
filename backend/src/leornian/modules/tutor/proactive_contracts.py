from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator

from leornian.shared_kernel.contracts import Contract


class ProactivePreferenceInput(Contract):
    expected_revision: int = Field(ge=0)
    enabled: bool
    timezone: str = Field(default="UTC", max_length=80)
    start_minute: int = Field(default=540, ge=0, le=1439)
    end_minute: int = Field(default=1260, ge=0, le=1439)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("Use an IANA timezone.") from error
        return value


class ProactivePreference(Contract):
    conversation_id: UUID
    revision: int
    enabled: bool
    timezone: str
    start_minute: int
    end_minute: int
    updated_at: datetime


def within_window(preference, now):
    local = now.astimezone(ZoneInfo(preference.timezone))
    minute = local.hour * 60 + local.minute
    start, end = preference.start_minute, preference.end_minute
    if start == end:
        return True
    if start < end:
        return start <= minute < end
    return minute >= start or minute < end
