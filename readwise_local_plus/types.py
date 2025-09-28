from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from readwise_local_plus.config import UserConfig
from readwise_local_plus.models import ReadwiseBatch

CheckDBFn = Callable[[Session, UserConfig], datetime | None]
FetchFn = Callable[[datetime | None], tuple[list[dict[str, Any]], datetime, datetime]]
FlattenFn = Callable[[list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]
SessionFn = Callable[[str | Path], Session]
UpdateDbFlatObjFn = Callable[
    [Session, dict[str, list[dict[str, Any]]], datetime, datetime], int | None
]
ValidateNestedObjFn = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
ValidateFlatObjFn = Callable[
    [dict[str, list[dict[str, Any]]]], dict[str, list[dict[str, Any]]]
]


@runtime_checkable
class ReadwiseAPIObject(Protocol):
    """
    Protocol for Readwise API objects.

    This protocol is used for static typing (e.g. with mypy) to indicate that an object
    has validation fields, batch fields and a 'dump_column_data' method.
    """

    validated: bool
    validation_errors: dict[str, str]
    batch_id: int
    batch: "ReadwiseBatch"

    def dump_column_data(self, exclude: Optional[set[str]] = None) -> dict[str, str]:
        """Dump column fields and values to a dict."""
        ...
