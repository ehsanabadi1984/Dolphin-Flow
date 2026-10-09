from collections import defaultdict

from workflow.form_field_value_resolution_services import FormFieldValueResolver
from workflow.formula_services import FormulaService
from workflow.models import FormField
from workflow.permission_context import PermissionContext
from workflow.process_summary_services import ProcessSummaryService
from workflow.process_summary_batch_context_services import (
    ProcessSummaryBatchContextService,
)
from workflow.repeatable_row_read_services import RepeatableRowReadService


class ProcessFormSearchService:
    """Search persisted form values that are visible to the requesting user."""

    @classmethod
    def matching_instance_ids(cls, *, queryset, user, term):
        term = cls._normalize(term)
        if not term:
            return set()

        instances = list(
            queryset.select_related("workflow", "current_step").distinct()
        )
        if not instances:
            return set()

        context = ProcessSummaryBatchContextService.build(instances=instances)
        summary_steps = ProcessSummaryService._summary_steps_for_instances(
            instances,
            user=user,
        )
        scopes = []
        for instance in instances:
            form = context["forms"].get(instance.workflow_id)
            step = instance.current_step or summary_steps.get(instance.pk)
            if form is None or step is None:
                continue
            scopes.append({
                "workflow": instance.workflow,
                "form": form,
                "step": step,
                "user": user,
            })

        step_permissions = PermissionContext.build_batch(scopes=scopes)
        permissions_by_instance = {}
        for instance in instances:
            form = context["forms"].get(instance.workflow_id)
            step = instance.current_step or summary_steps.get(instance.pk)
            if form is None or step is None:
                continue
            key = (
                instance.workflow_id,
                form.pk,
                step.pk,
                user.pk,
            )
            permissions_by_instance[instance.pk] = step_permissions.get(key)

        fields_by_instance = {}
        search_data_by_instance = {}
        for instance in instances:
            form = context["forms"].get(instance.workflow_id)
            permission = permissions_by_instance.get(instance.pk)
            if form is None or permission is None:
                continue

            data = dict(context["form_data"].get(instance.pk, {}) or {})
            sections = context["sections"].get(instance.workflow_id, [])
            fields = []
            has_normal_formula = False
            groups_by_section = defaultdict(list)
            children_by_parent = defaultdict(list)
            for group in context["groups"].get(instance.workflow_id, []):
                groups_by_section[group.section_id].append(group)
                if group.parent_group_id is not None:
                    children_by_parent[group.parent_group_id].append(group)

            for section in sections:
                for field in section.fields.all():
                    if not field.is_active:
                        continue
                    if (
                        field.repeatable_group_id is None
                        and not permission.is_field_hidden(field)
                    ):
                        fields.append(field)
                        if field.field_type == FormField.FieldType.FORMULA:
                            has_normal_formula = True

            if has_normal_formula:
                root_groups = [
                    group
                    for section in sections
                    for group in groups_by_section.get(section.pk, [])
                    if group.parent_group_id is None
                ]
                all_groups = ProcessSummaryService._flatten_groups(
                    root_groups,
                    children_by_parent=children_by_parent,
                )
                formula_repeatable_data = (
                    ProcessSummaryService._build_formula_repeatable_data(
                        groups=all_groups,
                        rows_by_group_parent=context["rows_by_instance"].get(
                            instance.pk, {}
                        ),
                        model_reference_cache=context["model_reference_cache"],
                    )
                )
                formula_data = dict(data)
                formula_data.update(formula_repeatable_data)
                data = FormulaService.calculate_context_data(
                    form=form,
                    data=formula_data,
                )

            search_data_by_instance[instance.pk] = data
            fields_by_instance[instance.pk] = fields

        display_cache = FormFieldValueResolver.build_display_cache_batch(
            fields_by_instance=fields_by_instance,
            data_by_instance=search_data_by_instance,
        )

        groups_by_workflow = context["groups"]
        matched = set()
        for instance in instances:
            permission = permissions_by_instance.get(instance.pk)
            if permission is None:
                continue

            data = search_data_by_instance.get(instance.pk, {})
            for field in fields_by_instance.get(instance.pk, []):
                raw_value = data.get(field.code)
                display_value = FormFieldValueResolver.get_display_value(
                    field=field,
                    value=raw_value,
                    display_cache=display_cache,
                )
                if cls._field_matches(
                    field=field,
                    raw_value=raw_value,
                    display_value=display_value,
                    term=term,
                ):
                    matched.add(instance.pk)
                    break
            if instance.pk in matched:
                continue

            groups = groups_by_workflow.get(instance.workflow_id, [])
            children_by_parent = defaultdict(list)
            roots = []
            for group in groups:
                if group.parent_group_id is None:
                    roots.append(group)
                else:
                    children_by_parent[group.parent_group_id].append(group)

            rows_by_group_parent = context["rows_by_instance"].get(
                instance.pk, {}
            )
            model_reference_cache = context["model_reference_cache"]

            def search_group(group, parent_row_id=None, parent_hidden=False):
                if parent_hidden or permission.is_group_hidden(group):
                    return False

                fields = [
                    field for field in group.fields.all()
                    if field.is_active and not permission.is_field_hidden(field)
                ]
                rows = rows_by_group_parent.get(
                    (group.pk, parent_row_id), []
                )
                for row in rows:
                    values_by_field_id = {
                        item.field_id: item for item in row.values.all()
                    }
                    for field in fields:
                        value_object = values_by_field_id.get(field.pk)
                        if field.system_key != FormField.SystemKey.NONE:
                            raw_value, display_value = (
                                RepeatableRowReadService._system_value(
                                    row=row,
                                    field=field,
                                )
                            )
                        else:
                            raw_value, display_value = (
                                RepeatableRowReadService._custom_value(
                                    field=field,
                                    value_object=value_object,
                                    model_reference_cache=model_reference_cache,
                                )
                            )
                        if cls._field_matches(
                            field=field,
                            raw_value=raw_value,
                            display_value=display_value,
                            term=term,
                        ):
                            return True

                    for child in children_by_parent.get(group.pk, []):
                        if search_group(child, parent_row_id=row.pk):
                            return True
                return False

            if any(search_group(group) for group in roots):
                matched.add(instance.pk)

        return matched

    @classmethod
    def _field_matches(cls, *, field, raw_value, display_value, term):
        if cls._contains_term(display_value, term):
            return True
        if field.field_type == FormField.FieldType.SELECT:
            return False
        if field.system_key in (
            FormField.SystemKey.DEVICE_TYPE,
            FormField.SystemKey.DEVICE_MODEL,
        ):
            return False
        return cls._contains_term(raw_value, term)

    @classmethod
    def _contains_term(cls, value, term):
        if value is None or value == "":
            return False
        if isinstance(value, dict):
            value = " ".join(str(item) for item in value.values())
        elif isinstance(value, (list, tuple, set)):
            value = " ".join(str(item) for item in value)
        return term in cls._normalize(value)

    @staticmethod
    def _normalize(value):
        value = str("" if value is None else value).strip().casefold()
        translation = str.maketrans({
            "ي": "ی",
            "ى": "ی",
            "ك": "ک",
            "٠": "0",
            "١": "1",
            "٢": "2",
            "٣": "3",
            "٤": "4",
            "٥": "5",
            "٦": "6",
            "٧": "7",
            "٨": "8",
            "٩": "9",
            "۰": "0",
            "۱": "1",
            "۲": "2",
            "۳": "3",
            "۴": "4",
            "۵": "5",
            "۶": "6",
            "۷": "7",
            "۸": "8",
            "۹": "9",
        })
        return value.translate(translation)
