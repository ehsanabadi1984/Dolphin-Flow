from collections import defaultdict

from .form_services import DynamicFormService
from .models import FormData, FormField, FormRepeatableGroup
from .permission_context import PermissionContext
from .repeatable_row_read_services import RepeatableRowReadService


class ProcessSummaryService:
    """
    Resolve the small, permission-aware set of form values configured for
    process-card summaries.

    This service deliberately does not build the complete dynamic form.
    Repeatable values are read from RepeatableRowReadService and normal
    values are read directly from FormData.
    """

    @classmethod
    def get_for_instance(cls, *, instance, user, step=None):
        step = step or instance.current_step
        if step is None:
            return []

        form = getattr(instance.workflow, "form_definition", None)
        if form is None:
            return []

        permission_context = PermissionContext.build(
            workflow=instance.workflow,
            form=form,
            step=step,
            user=user,
        )

        sections = list(
            form.sections.filter(is_active=True)
            .prefetch_related(
                "fields",
                "repeatable_groups__fields",
                "repeatable_groups__child_groups__fields",
            )
            .order_by("order", "id")
        )

        form_data = (
            FormData.objects
            .filter(instance=instance)
            .first()
        )
        normal_data = form_data.data if form_data else {}

        summary = []

        for section in sections:
            normal_fields = [
                field
                for field in section.fields.all()
                if (
                    field.is_active
                    and field.repeatable_group_id is None
                    and field.show_in_process_summary
                    and not permission_context.is_field_hidden(field)
                )
            ]

            for field in sorted(
                normal_fields,
                key=lambda item: (item.order, item.id),
            ):
                value = normal_data.get(field.code)
                display_value = DynamicFormService._get_display_value(
                    field=field,
                    value=value,
                )
                if display_value in ("", None, []):
                    continue

                summary.append(
                    {
                        "label": field.label,
                        "value": display_value,
                    }
                )

            groups = [
                group
                for group in section.repeatable_groups.all()
                if group.is_active and group.parent_group_id is None
            ]

            rows_by_group_parent = RepeatableRowReadService.get_rows_by_group_parent(
                instance=instance,
                groups=cls._flatten_groups(groups),
            )

            for group in sorted(
                groups,
                key=lambda item: (item.order, item.id),
            ):
                rendered = cls._render_group(
                    group=group,
                    parent_row_id=None,
                    rows_by_group_parent=rows_by_group_parent,
                    permission_context=permission_context,
                )
                if rendered is not None:
                    summary.append(rendered)

        return summary

    @staticmethod
    def _flatten_groups(groups):
        result = []

        def visit(group):
            result.append(group)
            for child in group.child_groups.filter(is_active=True).order_by(
                "order", "id"
            ):
                visit(child)

        for group in groups:
            visit(group)

        return result

    @classmethod
    def _render_group(
        cls,
        *,
        group,
        parent_row_id,
        rows_by_group_parent,
        permission_context,
    ):
        if permission_context.is_group_hidden(group):
            return None

        fields = [
            field
            for field in group.fields.all()
            if (
                field.is_active
                and field.show_in_process_summary
                and not permission_context.is_field_hidden(field)
            )
        ]
        fields.sort(key=lambda item: (item.order, item.id))

        child_groups = [
            child
            for child in group.child_groups.all()
            if child.is_active
        ]
        child_groups.sort(key=lambda item: (item.order, item.id))

        rows = rows_by_group_parent.get(
            (group.pk, parent_row_id),
            [],
        )

        rendered_rows = []
        for row in rows:
            items = []
            values_by_field_id = {
                item.field_id: item
                for item in row.values.all()
            }

            for field in fields:
                value_object = values_by_field_id.get(field.pk)

                if field.system_key != FormField.SystemKey.NONE:
                    value, display_value = (
                        RepeatableRowReadService._system_value(
                            row=row,
                            field=field,
                        )
                    )
                else:
                    value, display_value = (
                        RepeatableRowReadService._custom_value(
                            field=field,
                            value_object=value_object,
                        )
                    )

                if display_value in ("", None, []):
                    continue

                items.append(
                    {
                        "label": field.label,
                        "value": display_value,
                    }
                )

            children = []
            for child_group in child_groups:
                rendered_child = cls._render_group(
                    group=child_group,
                    parent_row_id=row.pk,
                    rows_by_group_parent=rows_by_group_parent,
                    permission_context=permission_context,
                )
                if rendered_child is not None:
                    children.append(rendered_child)

            if items or children:
                rendered_rows.append(
                    {
                        "row_id": row.pk,
                        "items": items,
                        "children": children,
                    }
                )

        if not rendered_rows:
            return None

        return {
            "group_label": group.label or group.name,
            "rows": rendered_rows,
        }
