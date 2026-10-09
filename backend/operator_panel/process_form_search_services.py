from collections import defaultdict

from workflow.form_field_value_resolution_services import FormFieldValueResolver
from workflow.formula_services import FormulaService
from workflow.models import FormField
from workflow.permission_context import PermissionContext
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
        scopes = []
        for instance in instances:
            form = context["forms"].get(instance.workflow_id)
            if form is None or instance.current_step_id is None:
                continue
            scopes.append({
                "workflow": instance.workflow,
                "form": form,
                "step": instance.current_step,
                "user": user,
            })

        step_permissions = PermissionContext.build_batch(scopes=scopes)
        no_step_scopes = []
        for instance in instances:
            form = context["forms"].get(instance.workflow_id)
            if form is not None and instance.current_step_id is None:
                no_step_scopes.append({
                    "workflow": instance.workflow,
                    "form": form,
                    "user": user,
                })
        no_step_permissions = PermissionContext.build_summary_batch(
            scopes=no_step_scopes,
        )

        permissions_by_instance = {}
        for instance in instances:
            form = context["forms"].get(instance.workflow_id)
            if form is None:
                continue
            if instance.current_step_id is not None:
                key = (
                    instance.workflow_id,
                    form.pk,
                    instance.current_step_id,
                    user.pk,
                )
                permissions_by_instance[instance.pk] = step_permissions.get(key)
            else:
                key = (instance.workflow_id, form.pk, user.pk)
                permissions_by_instance[instance.pk] = no_step_permissions.get(key)

        fields_by_instance = {}
        search_data_by_instance = {}
        for instance in instances:
            form = context["forms"].get(instance.workflow_id)
            permission = permissions_by_instance.get(instance.pk)
            if form is None or permission is None:
                continue

            data = dict(context["form_data"].get(instance.pk, {}) or {})
            data = FormulaService.calculate_context_data(form=form, data=data)
            search_data_by_instance[instance.pk] = data

            fields = []
            for section in context["sections"].get(instance.workflow_id, []):
                for field in section.fields.all():
                    if (
                        field.is_active
                        and field.repeatable_group_id is None
                        and not permission.is_field_hidden(field)
                    ):
                        fields.append(field)
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
                if cls._contains_term(raw_value, term) or cls._contains_term(
                    display_value, term
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
                        if cls._contains_term(raw_value, term) or cls._contains_term(
                            display_value, term
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
    def _contains_term(cls, value, term):
        if value in (None, ""):
            return False
        if isinstance(value, dict):
            value = " ".join(str(item) for item in value.values())
        elif isinstance(value, (list, tuple, set)):
            value = " ".join(str(item) for item in value)
        return term in cls._normalize(value)

    @staticmethod
    def _normalize(value):
        value = str(value or "").strip().casefold()
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
