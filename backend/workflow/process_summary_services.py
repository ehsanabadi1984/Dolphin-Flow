from collections import defaultdict

from .form_field_value_resolution_services import FormFieldValueResolver
from .formula_services import FormulaService
from .models import FormData, FormField, FormRepeatableGroup, WorkflowStepExecution
from .permission_context import PermissionContext
from .process_summary_batch_context_services import ProcessSummaryBatchContextService
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
            step = cls._summary_step_for_instance(instance, user=user)
        if step is None:
            return []

        context = ProcessSummaryBatchContextService.build(instances=[instance])
        return cls._render_instance(
            instance=instance,
            user=user,
            step=step,
            context=context,
        )

    @classmethod
    def get_for_instances(cls, *, instances, user):
        instances = list(instances)
        if not instances:
            return {}

        context = ProcessSummaryBatchContextService.build(instances=instances)

        summary_steps = cls._summary_steps_for_instances(instances, user=user)
        scopes = []
        fields_by_instance = {}
        for instance in instances:
            step = instance.current_step or summary_steps.get(instance.pk)
            form = context["forms"].get(instance.workflow_id)
            if step is None or form is None:
                fields_by_instance[instance.pk] = []
                continue

            scopes.append(
                {
                    "workflow": instance.workflow,
                    "form": form,
                    "step": step,
                    "user": user,
                }
            )

        permission_contexts = PermissionContext.build_batch(scopes=scopes)

        for instance in instances:
            step = instance.current_step or summary_steps.get(instance.pk)
            form = context["forms"].get(instance.workflow_id)
            if step is None or form is None:
                fields_by_instance[instance.pk] = []
                continue

            key = (instance.workflow_id, form.pk, step.pk, user.pk)
            fields_by_instance[instance.pk] = cls._summary_normal_fields(
                sections=context["sections"].get(instance.workflow_id, []),
                permission_context=permission_contexts[key],
            )

        normal_display_cache = FormFieldValueResolver.build_display_cache_batch(
            fields_by_instance=fields_by_instance,
            data_by_instance=context["form_data"],
        )

        summaries = {}
        for instance in instances:
            form = context["forms"].get(instance.workflow_id)
            step = instance.current_step or summary_steps.get(instance.pk)
            permission_context = None
            if form is not None and step is not None:
                permission_context = permission_contexts[
                    (instance.workflow_id, form.pk, step.pk, user.pk)
                ]

            summaries[instance.pk] = cls._render_instance(
                instance=instance,
                user=user,
                step=step,
                context=context,
                permission_context=permission_context,
                normal_display_cache=normal_display_cache,
            )

        return summaries

    @staticmethod
    def _summary_step_for_instance(instance, *, user):
        execution = (
            WorkflowStepExecution.objects
            .filter(
                instance_id=instance.pk,
                performed_by_id=user.pk,
            )
            .select_related("workflow_step")
            .order_by("-performed_at", "-pk")
            .first()
        )
        return execution.workflow_step if execution else None

    @staticmethod
    def _summary_steps_for_instances(instances, *, user):
        instance_ids = [instance.pk for instance in instances]
        if not instance_ids:
            return {}

        steps_by_instance = {}
        executions = (
            WorkflowStepExecution.objects
            .filter(
                instance_id__in=instance_ids,
                performed_by_id=user.pk,
            )
            .select_related("workflow_step")
            .order_by("instance_id", "-performed_at", "-pk")
        )
        for execution in executions:
            steps_by_instance.setdefault(
                execution.instance_id,
                execution.workflow_step,
            )
        return steps_by_instance

    @classmethod
    def _render_instance(
        cls,
        *,
        instance,
        user,
        step,
        context,
        permission_context=None,
        normal_display_cache=None,
    ):
        if step is None:
            return []

        form = context["forms"].get(instance.workflow_id)
        if form is None:
            return []

        if permission_context is None:
            permission_context = PermissionContext.build(
                workflow=instance.workflow,
                form=form,
                step=step,
                user=user,
            )

        sections = context["sections"].get(instance.workflow_id, [])
        repeatable_groups = context["groups"].get(instance.workflow_id, [])

        groups_by_section = defaultdict(list)
        children_by_parent = defaultdict(list)
        for group in repeatable_groups:
            groups_by_section[group.section_id].append(group)
            if group.parent_group_id is not None:
                children_by_parent[group.parent_group_id].append(group)

        normal_data = context["form_data"].get(instance.pk, {})

        all_groups = cls._flatten_groups(
            [
                group
                for section in sections
                for group in groups_by_section.get(section.pk, [])
                if group.parent_group_id is None
            ],
            children_by_parent=children_by_parent,
        )
        rows_by_group_parent = context["rows_by_instance"].get(
            instance.pk,
            {},
        )
        model_reference_cache = context["model_reference_cache"]
        formula_repeatable_data = cls._build_formula_repeatable_data(
            groups=all_groups,
            rows_by_group_parent=rows_by_group_parent,
            model_reference_cache=model_reference_cache,
        )
        formula_data = dict(normal_data)
        formula_data.update(formula_repeatable_data)
        normal_data = FormulaService.calculate_context_data(
            form=form,
            data=formula_data,
        )

        summary = []
        normal_fields_by_section = {}
        all_normal_fields = []

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
            normal_fields.sort(key=lambda item: (item.order, item.id))
            normal_fields_by_section[section.pk] = normal_fields
            all_normal_fields.extend(normal_fields)

        if normal_display_cache is None:
            normal_display_cache = FormFieldValueResolver.build_display_cache(
                fields=all_normal_fields,
                data=normal_data,
            )

        for section in sections:
            for field in normal_fields_by_section.get(section.pk, []):
                value = normal_data.get(field.code)
                display_value = FormFieldValueResolver.get_display_value(
                    field=field,
                    value=value,
                    display_cache=normal_display_cache,
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
                for group in groups_by_section.get(section.pk, [])
                if group.parent_group_id is None
            ]

            for group in sorted(
                groups,
                key=lambda item: (item.order, item.id),
            ):
                rendered = cls._render_group(
                    group=group,
                    parent_row_id=None,
                    rows_by_group_parent=rows_by_group_parent,
                    permission_context=permission_context,
                    model_reference_cache=model_reference_cache,
                    children_by_parent=children_by_parent,
                )
                if rendered is not None:
                    summary.append(rendered)

        return summary

    @staticmethod
    def _summary_normal_fields(*, sections, permission_context):
        fields = []
        for section in sections:
            fields.extend(
                field
                for field in section.fields.all()
                if (
                    field.is_active
                    and field.repeatable_group_id is None
                    and field.show_in_process_summary
                    and not permission_context.is_field_hidden(field)
                )
            )
        fields.sort(key=lambda item: (item.order, item.id))
        return fields

    @staticmethod
    def _build_formula_repeatable_data(
        *,
        groups,
        rows_by_group_parent,
        model_reference_cache,
    ):
        children_by_group = defaultdict(list)
        for group in groups:
            if group.parent_group_id is not None:
                children_by_group[group.parent_group_id].append(group)

        def build_group(group, parent_row_id=None):
            rows = rows_by_group_parent.get((group.pk, parent_row_id), [])
            items = []
            for row in rows:
                values_by_field_id = {
                    item.field_id: item
                    for item in row.values.all()
                }
                payload = {}
                for field in group.fields.all():
                    if field.system_key != FormField.SystemKey.NONE:
                        continue
                    if field.field_type == FormField.FieldType.FORMULA:
                        continue
                    value_object = values_by_field_id.get(field.pk)
                    value, _ = RepeatableRowReadService._custom_value(
                        field=field,
                        value_object=value_object,
                        model_reference_cache=model_reference_cache,
                    )
                    payload[field.code] = value

                child_payloads = []
                for child_group in children_by_group.get(group.pk, []):
                    child_payloads.append(
                        build_group(
                            child_group,
                            parent_row_id=row.pk,
                        )
                    )
                if child_payloads:
                    payload["child_groups"] = child_payloads

                items.append(payload)

            return {
                "code": group.code,
                "items": items,
            }

        return {
            group.code: build_group(group)
            for group in groups
            if group.parent_group_id is None
        }

    @staticmethod
    def _flatten_groups(groups, *, children_by_parent):
        result = []

        def visit(group):
            result.append(group)
            for child in children_by_parent.get(group.pk, []):
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
        model_reference_cache,
        children_by_parent,
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

        child_groups = list(children_by_parent.get(group.pk, []))

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
                            model_reference_cache=model_reference_cache,
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
                    model_reference_cache=model_reference_cache,
                    children_by_parent=children_by_parent,
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
