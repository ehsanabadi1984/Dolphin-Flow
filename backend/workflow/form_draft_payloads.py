from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizedRow:
    row_id: int | None
    fields: dict[str, Any]
    child_groups: dict[str, tuple["NormalizedRow", ...]]


@dataclass(frozen=True)
class NormalizedFormPayload:
    normal_fields: dict[str, Any]
    repeatable_groups: dict[str, tuple[NormalizedRow, ...]]
