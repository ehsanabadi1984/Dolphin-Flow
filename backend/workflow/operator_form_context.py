"""Presentation context contracts for the operator form.

This module defines the boundary between DynamicFormService/application
logic and OperatorFormSerializer/template presentation.

The contracts intentionally use TypedDicts rather than runtime DTOs. This
lets the current dictionary-based template contract migrate incrementally
without changing template behaviour or introducing a second source of truth.

Canonical ownership rules:
- scalar top-level values: FormData.data
- normal/device repeatable rows: RepeatableRow / RepeatableRowValue
- device identity/state: InstanceDevice / Device
- files: FormFile, associated with RepeatableRow where applicable
- formula results: backend-calculated values
"""

from __future__ import annotations

from typing import Any, Mapping, NotRequired, TypedDict


class PermissionViewContext(TypedDict):
    """Effective permissions already resolved for presentation."""

    can_view: bool
    can_edit: bool
    can_add: NotRequired[bool]
    can_delete: NotRequired[bool]


class FieldContext(TypedDict):
    """Application context for one visible form field.

    'field' remains the FormField model instance. Values come from the
    canonical source appropriate to the field; this contract does not decide
    persistence.
    """

    field: Any
    can_edit: bool
    permission_can_edit: bool
    value: Any
    display_value: str
    choices: list[Mapping[str, Any]]
    parent_code: str | None
    device_types: NotRequired[Any]
    device_models: NotRequired[Any]
    is_immutable: NotRequired[bool]
    is_imei_immutable: NotRequired[bool]
    file: NotRequired[Any]
    files: NotRequired[list[Any]]


class DeviceContext(TypedDict):
    """Application context for a device repeatable row.

    Device identity/state is deliberately separate from RepeatableRowValue.
    """

    instance_device: Any
    device: NotRequired[Any]
    draft_device: NotRequired[Any]
    device_id: NotRequired[Any]
    instance_device_id: NotRequired[Any]
    device_type: NotRequired[Any]
    device_model: NotRequired[Any]
    identifiers: NotRequired[list[Mapping[str, Any]]]
    imei: NotRequired[str]
    warranty: NotRequired[Any]
    warranty_status: NotRequired[Any]
    status: NotRequired[Any]
    reported_problem: NotRequired[str]
    description: NotRequired[str]
    is_existing_device: bool
    has_history: bool


class RowContext(TypedDict):
    """Application context for one canonical RepeatableRow."""

    row_id: str
    row_order: int
    parent_row_id: str | None
    fields: list[FieldContext]
    child_groups: NotRequired[list["GroupContext"]]
    device: NotRequired[DeviceContext]


class GroupContext(TypedDict):
    """Application/presentation boundary for one RepeatableGroup."""

    group: Any
    fields: list[FieldContext]
    items: list[RowContext]
    permissions: PermissionViewContext
    has_editable_fields: bool
    display_type: str
    group_type: str
    child_groups: NotRequired[list["GroupContext"]]


class SectionContext(TypedDict):
    """Application context for one visible form section."""

    section: Any
    fields: list[Mapping[str, Any]]
    repeatable_groups: list[Mapping[str, Any]]
    layout_items: list[Mapping[str, Any]]


class FormContext(TypedDict):
    """Top-level context consumed by OperatorFormSerializer.

    This is intentionally not a persistence DTO. It describes what the
    operator form needs to render, while canonical data remains owned by the
    application/domain services.
    """

    form: Any
    sections: list[SectionContext]
    is_submitted: bool
    edit_mode: bool
    validation_errors: NotRequired[list[Mapping[str, Any]]]
