from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from .form_draft_payloads import NormalizedFormPayload, NormalizedRow
from .models import FormData, FormRepeatableGroup, RepeatableRow


class RowChangeAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class RowReferenceKind(StrEnum):
    EXISTING = "existing"
    CREATE = "create"


@dataclass(frozen=True)
class RowReference:
    kind: RowReferenceKind
    value: int | str


@dataclass(frozen=True)
class RowChange:
    action: RowChangeAction
    group: FormRepeatableGroup
    row_id: int | None
    desired_row: NormalizedRow | None
    row_reference: RowReference
    parent_reference: RowReference | None


@dataclass(frozen=True)
class RepeatableGroupDiff:
    group: FormRepeatableGroup
    changes: tuple[RowChange, ...]


@dataclass(frozen=True)
class NormalFieldChange:
    field: object
    submitted_value: object
    persisted_value: object
    changed: bool


@dataclass(frozen=True)
class FormDraftDiff:
    normal_fields: tuple[NormalFieldChange, ...]
    groups: tuple[RepeatableGroupDiff, ...]


class FormDraftDiffService:
    """
    Compare the persisted RepeatableRow tree with the submitted desired state.

    This service is intentionally side-effect free:
    - no permissions
    - no validation beyond the identity contract already enforced by
      FormDraftSaveService
    - no persistence
    - no field-level diffing

    A repeatable group that is absent from the payload is untouched.
    A group explicitly present with [] means that all persisted rows in
    that group are part of the DELETE diff.
    """

    @classmethod
    def build(
        cls,
        *,
        instance,
        form,
        normalized_payload: NormalizedFormPayload,
    ) -> FormDraftDiff:
        groups_by_code = {
            group.code: group
            for section in form.sections.filter(is_active=True)
            for group in section.repeatable_groups.filter(
                is_active=True,
                parent_group__isnull=True,
            )
        }

        normal_field_changes = cls._diff_normal_fields(
            instance=instance,
            form=form,
            normalized_payload=normalized_payload,
        )

        group_diffs = []

        for group_code, desired_rows in normalized_payload.repeatable_groups.items():
            group = groups_by_code[group_code]
            changes = []
            cls._diff_group(
                instance=instance,
                group=group,
                desired_rows=desired_rows,
                parent_reference=None,
                changes=changes,
            )
            group_diffs.append(
                RepeatableGroupDiff(
                    group=group,
                    changes=tuple(changes),
                )
            )

        return FormDraftDiff(
            normal_fields=tuple(normal_field_changes),
            groups=tuple(group_diffs),
        )

    @classmethod
    def _diff_normal_fields(
        cls,
        *,
        instance,
        form,
        normalized_payload,
    ):
        form_data = (
            FormData.objects
            .filter(instance=instance)
            .first()
        )
        persisted_data = (
            form_data.data
            if form_data is not None and isinstance(form_data.data, dict)
            else {}
        )

        fields = [
            field
            for section in form.sections.filter(is_active=True)
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            )
        ]

        changes = []
        for field in fields:
            if field.code not in normalized_payload.normal_fields:
                continue

            submitted_value = normalized_payload.normal_fields[field.code]
            persisted_value = persisted_data.get(field.code)
            changes.append(
                NormalFieldChange(
                    field=field,
                    submitted_value=submitted_value,
                    persisted_value=persisted_value,
                    changed=submitted_value != persisted_value,
                )
            )

        return changes

    @classmethod
    def _diff_group(
        cls,
        *,
        instance,
        group,
        desired_rows,
        parent_reference,
        changes,
    ):
        persisted_rows = cls._get_sibling_rows(
            instance=instance,
            group=group,
            parent_reference=parent_reference,
        )
        persisted_by_id = {row.pk: row for row in persisted_rows}
        desired_existing_ids = {
            row.row_id
            for row in desired_rows
            if row.row_id is not None
        }

        for desired_row in desired_rows:
            if desired_row.row_id is None:
                create_reference = RowReference(
                    kind=RowReferenceKind.CREATE,
                    value=str(uuid4()),
                )
                changes.append(
                    RowChange(
                        action=RowChangeAction.CREATE,
                        group=group,
                        row_id=None,
                        desired_row=desired_row,
                        row_reference=create_reference,
                        parent_reference=parent_reference,
                    )
                )
                cls._diff_child_groups(
                    instance=instance,
                    group=group,
                    desired_row=desired_row,
                    parent_reference=create_reference,
                    changes=changes,
                )
                continue

            persisted_row = persisted_by_id[desired_row.row_id]
            existing_reference = RowReference(
                kind=RowReferenceKind.EXISTING,
                value=persisted_row.pk,
            )
            changes.append(
                RowChange(
                    action=RowChangeAction.UPDATE,
                    group=group,
                    row_id=persisted_row.pk,
                    desired_row=desired_row,
                    row_reference=existing_reference,
                    parent_reference=parent_reference,
                )
            )
            cls._diff_child_groups(
                instance=instance,
                group=group,
                desired_row=desired_row,
                parent_reference=existing_reference,
                changes=changes,
            )

        for persisted_row in persisted_rows:
            if persisted_row.pk in desired_existing_ids:
                continue
            cls._append_delete_subtree(
                instance=instance,
                row=persisted_row,
                changes=changes,
            )

    @classmethod
    def _diff_child_groups(
        cls,
        *,
        instance,
        group,
        desired_row,
        parent_reference,
        changes,
    ):
        for child_group_code, child_rows in desired_row.child_groups.items():
            child_group = group.child_groups.get(
                code=child_group_code,
                is_active=True,
            )
            cls._diff_group(
                instance=instance,
                group=child_group,
                desired_rows=child_rows,
                parent_reference=parent_reference,
                changes=changes,
            )

    @classmethod
    def _append_delete_subtree(
        cls,
        *,
        instance,
        row,
        changes,
    ):
        child_groups = row.group.child_groups.filter(is_active=True)

        for child_group in child_groups:
            child_rows = (
                RepeatableRow.objects
                .filter(
                    instance=instance,
                    group=child_group,
                    parent_row=row,
                )
                .order_by("row_order", "id")
            )
            for child_row in child_rows:
                cls._append_delete_subtree(
                    instance=instance,
                    row=child_row,
                    changes=changes,
                )

        existing_reference = RowReference(
            kind=RowReferenceKind.EXISTING,
            value=row.pk,
        )
        parent_reference = None
        if row.parent_row_id is not None:
            parent_reference = RowReference(
                kind=RowReferenceKind.EXISTING,
                value=row.parent_row_id,
            )

        changes.append(
            RowChange(
                action=RowChangeAction.DELETE,
                group=row.group,
                row_id=row.pk,
                desired_row=None,
                row_reference=existing_reference,
                parent_reference=parent_reference,
            )
        )

    @staticmethod
    def _get_sibling_rows(*, instance, group, parent_reference):
        queryset = (
            RepeatableRow.objects
            .filter(
                instance=instance,
                group=group,
            )
            .order_by("row_order", "id")
        )

        if parent_reference is None:
            return queryset.filter(parent_row__isnull=True)

        if parent_reference.kind == RowReferenceKind.EXISTING:
            return queryset.filter(parent_row_id=parent_reference.value)

        # A newly-created parent cannot have persisted children.
        return queryset.none()
