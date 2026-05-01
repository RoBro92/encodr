from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.helpers.api import import_api_module


def test_schedule_window_request_accepts_exact_hh_mm_times() -> None:
    with import_api_module("app.schemas.schedules") as schedules:
        window = schedules.ScheduleWindowRequest(
            days=[" Mon ", "mon", "FRI"],
            start_time="07:00",
            end_time="18:30",
        )

    assert window.days == ["mon", "fri"]
    assert window.start_time == "07:00"
    assert window.end_time == "18:30"


@pytest.mark.parametrize(
    "bad_time",
    [
        "24:00",
        "23:60",
        "7:00",
        "07:0",
        "7:000",
        " 07:00",
        "07:00 ",
        "aa:bb",
        "12-30",
    ],
)
def test_schedule_window_request_rejects_invalid_start_times(bad_time: str) -> None:
    with import_api_module("app.schemas.schedules") as schedules:
        with pytest.raises(ValidationError):
            schedules.ScheduleWindowRequest(days=["mon"], start_time=bad_time, end_time="08:00")


def test_schedule_window_request_rejects_invalid_end_time() -> None:
    with import_api_module("app.schemas.schedules") as schedules:
        with pytest.raises(ValidationError):
            schedules.ScheduleWindowRequest(days=["mon"], start_time="07:00", end_time="25:00")
