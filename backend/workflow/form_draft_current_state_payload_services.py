from django.core.exceptions import ValidationError

from .form_draft_payloads import NormalizedFormPayload, NormalizedRow
from .models import FormData, FormRepeatableGroup, WorkflowInstance
from .repeatable_row_read_services import RepeatableRowReadService


class FormDraftCurrentStatePayloadService:
    """
    Build a complete NormalizedFormPayload from the canonical persisted state.

    This adapter is intentionally read-only. It does not perform validation,
    permission checks, or persistence.

    Normal fields are reconstructed from FormData. Repeatable groups and rows
    are reconstructed from RepeatableRow/RepeatableRowValue through
    RepeatableRowReadService, including nested groups and DEVICE system
    fields.

    Unlike the Save payload, the resulting payload is complete: every active
    normal field and every active root repeatable group is represented. Empty
    values/groups are represented explicitly as empty values/tuples.
    """

    @classmethod
    def build(
        cls,
        *,
        instance,
        form,
    ) -> NormalizedFormPayload:
        if instance is None or instance.pk is None:
            raise ValidationError("WorkflowInstance معتبر نیست.")

        if form is None or form.pk is None:
            raise ValidationError("فرم معتبر نیست.")

        if form.workflow_id != instance.workflow_id:
            raise ValidationError(
                "فرم و WorkflowInstance باید متعلق به یک Workflow باشند."
            )

        form_data = (
            FormData.objects
            .filter(instance=instance)
            .first()
        )
        persisted_normal_values = (
            (form_data.data or {})
            if form_data is not None
            else {}
        )

        normal_fields = {}
        for section in form.sections.filter(is_active=True).order_by("order", "id"):
            for field in section.fields.filter(
                is_active=True,
                repeatable_group__isnull=True,
            ).order_by("order", "id"):
                normal_fields[field.code] = persisted_normal_values.get(
                    field.code,
                    "",
                )

        repeatable_groups = {}

        root_groups = (
            FormRepeatableGroup.objects
            .filter(
                section__form=form,
                section__is_active=True,
                parent_group__isnull=True,
                is_active=True,
            )
            .select_related("section")
            .order_by(
                "section__order",
                "order",
                "id",
            )
        )

        for group in root_groups:
            reconstructed = RepeatableRowReadService.reconstruct_group(
                instance=instance,
                group=group,
            )
            repeatable_groups[group.code] = tuple(
                cls._normalize_row(item)
                for item in reconstructed["items"]
            )

        return NormalizedFormPayload(
            normal_fields=normal_fields,
            repeatable_groups=repeatable_groups,
        )

    @classmethod
    def _normalize_row(cls, reconstructed_row):
        child_groups = {}

        for child_group in reconstructed_row.get("child_groups", []):
            child_groups[child_group["code"]] = tuple(
                cls._normalize_row(item)
                for item in child_group.get("items", [])
            )

        fields = {
            item["code"]: item["value"]
            for item in reconstructed_row.get("fields", [])
        }

        return NormalizedRow(
            row_id=reconstructed_row["row_id"],
            fields=fields,
            child_groups=child_groups,
        )
