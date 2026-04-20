from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SqlEnum


def enum_type(enum_class: type[Enum], name: str) -> SqlEnum:
    return SqlEnum(
        enum_class,
        name=name,
        native_enum=False,
        validate_strings=True,
        create_constraint=True,
    )
