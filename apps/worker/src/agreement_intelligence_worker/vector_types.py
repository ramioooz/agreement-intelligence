from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql.base import PGDialect
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.types import TypeDecorator, UserDefinedType


class _PostgresVector(UserDefinedType[list[float]]):
    cache_ok = True

    def get_col_spec(self, **kwargs: object) -> str:
        del kwargs
        return "vector"

    def bind_processor(self, dialect: Dialect) -> Callable[[object], str | None]:
        del dialect

        def process(value: object) -> str | None:
            if value is None:
                return None
            vector = cast(list[float], value)
            return "[" + ",".join(str(component) for component in vector) + "]"

        return process

    def result_processor(
        self, dialect: Dialect, coltype: object
    ) -> Callable[[object], list[float] | None]:
        del dialect, coltype

        def process(value: object) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(component) for component in value]
            return [float(component) for component in json.loads(cast(str, value))]

        return process


class Vector(TypeDecorator[list[float]]):
    """A pgvector column in PostgreSQL and JSON-compatible test storage elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if isinstance(dialect, PGDialect):
            return dialect.type_descriptor(_PostgresVector())  # type: ignore[no-untyped-call]
        return dialect.type_descriptor(JSON())
