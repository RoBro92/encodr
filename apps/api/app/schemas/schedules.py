from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ScheduleWindowRequest(BaseModel):
    days: list[str] = Field(default_factory=list)
    start_time: str = Field(min_length=5, max_length=5)
    end_time: str = Field(min_length=5, max_length=5)

    @field_validator("days")
    @classmethod
    def validate_days(cls, value: list[str]) -> list[str]:
        supported = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        cleaned: list[str] = []
        for item in value:
            day = item.strip().lower()
            if day not in supported:
                raise ValueError(f"Unsupported day '{item}'.")
            if day not in cleaned:
                cleaned.append(day)
        if not cleaned:
            raise ValueError("At least one day must be selected.")
        return cleaned

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        if len(value) != 5 or value[2] != ":" or not value[:2].isdigit() or not value[3:].isdigit():
            raise ValueError("Schedule times must use HH:MM format.")
        hour = int(value[:2])
        minute = int(value[3:])
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError("Schedule times must use HH:MM format.")
        return value


class ScheduleWindowResponse(BaseModel):
    days: list[str]
    start_time: str
    end_time: str
