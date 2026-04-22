from __future__ import annotations

from datetime import datetime, time
from typing import Any

DAY_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def normalise_schedule_windows(value: Any) -> list[dict] | None:
    if value in (None, "", []):
        return None
    if not isinstance(value, list):
        raise ValueError("Schedule windows must be a list.")

    windows: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Schedule windows must contain objects.")
        days = item.get("days") or []
        if not isinstance(days, list) or not days:
            raise ValueError("Each schedule window must include at least one day.")
        cleaned_days: list[str] = []
        for day in days:
            cleaned = str(day).strip().lower()
            if cleaned not in DAY_ORDER:
                raise ValueError(f"Unsupported schedule day '{day}'.")
            if cleaned not in cleaned_days:
                cleaned_days.append(cleaned)
        start_time = _normalise_time(item.get("start_time"))
        end_time = _normalise_time(item.get("end_time"))
        windows.append(
            {
                "days": cleaned_days,
                "start_time": start_time,
                "end_time": end_time,
            }
        )
    return windows or None


def schedule_windows_allow_now(windows: list[dict] | None, *, now: datetime | None = None) -> bool:
    if not windows:
        return True
    current = now.astimezone() if now is not None else datetime.now().astimezone()
    day = DAY_ORDER[current.weekday()]
    clock = current.time().replace(tzinfo=None)
    for window in windows:
        days = {str(item).strip().lower() for item in window.get("days", [])}
        start_time = _parse_time(str(window.get("start_time")))
        end_time = _parse_time(str(window.get("end_time")))
        if start_time <= end_time:
            if day in days and start_time <= clock <= end_time:
                return True
            continue
        if day in days and clock >= start_time:
            return True
        previous_day = DAY_ORDER[(current.weekday() - 1) % 7]
        if previous_day in days and clock <= end_time:
            return True
    return False


def schedule_windows_summary(windows: list[dict] | None) -> str | None:
    if not windows:
        return None
    parts: list[str] = []
    for window in windows:
        day_text = ",".join(window.get("days", []))
        parts.append(f"{day_text} {window.get('start_time')}-{window.get('end_time')}")
    return " | ".join(parts)


def next_schedule_opening(windows: list[dict] | None, *, now: datetime | None = None) -> datetime | None:
    if not windows:
        return None
    current = now.astimezone() if now is not None else datetime.now().astimezone()
    if schedule_windows_allow_now(windows, now=current):
        return current
    candidates: list[datetime] = []
    for offset in range(0, 8):
        candidate_day = current.date().toordinal() + offset
        candidate = datetime.fromordinal(candidate_day).replace(
            hour=current.hour,
            minute=current.minute,
            second=current.second,
            microsecond=current.microsecond,
            tzinfo=current.tzinfo,
        )
        weekday = DAY_ORDER[candidate.weekday()]
        for window in windows:
            if weekday not in {str(item).strip().lower() for item in window.get("days", [])}:
                continue
            start_time = _parse_time(str(window.get("start_time")))
            opening = candidate.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
            if opening >= current:
                candidates.append(opening)
    return min(candidates) if candidates else None


def _normalise_time(value: Any) -> str:
    return _parse_time(str(value).strip()).strftime("%H:%M")


def _parse_time(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except Exception as error:  # noqa: BLE001
        raise ValueError("Schedule times must use HH:MM format.") from error
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("Schedule times must use HH:MM format.")
    return time(hour=hour, minute=minute)
