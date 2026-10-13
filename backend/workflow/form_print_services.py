from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .authorization import WorkflowAuthorizationService
from .form_services import DynamicFormService
from .models import (
    FormPrintFieldSettings,
    FormPrintSectionSettings,
    FormPrintSettings,
    FormRepeatableGroup,
    WorkflowPermission,
)


class FormPrintDataService:
    """
    Prepare a minimal, permission-filtered data structure for a printable form.

    DynamicFormService is the source of field values and repeatable-row
    reconstruction. It already applies the existing field/group visibility
    rules for the requested workflow step. This service only copies values
    from that visible context and applies print-specific configuration.
    """

    @classmethod
    def prepare(cls, *, instance, user, step=None):
        step = step or instance.current_step
        if step is None:
            raise PermissionDenied("برای چاپ، مرحلهٔ قابل مشاهده‌ای از فرایند مشخص نیست.")

        if not WorkflowAuthorizationService.has_permission(
            user=user,
            workflow=instance.workflow,
            action=WorkflowPermission.Action.VIEW,
            step=step,
            instance=instance,
        ):
            raise PermissionDenied("شما اجازه مشاهده و چاپ این فرایند را ندارید.")

        dynamic_form = DynamicFormService.get_form_for_step(
            instance=instance,
            user=user,
            edit_mode=False,
            read_context_step=step,
        )
        if not dynamic_form:
            return None

        form = dynamic_form["form"]
        settings = FormPrintSettings.objects.filter(form=form).first()
        show_empty_values = settings.show_empty_values if settings else False

        section_settings = {
            item.section_id: item
            for item in FormPrintSectionSettings.objects.filter(
                section__form=form,
            )
        }
        field_settings = {
            (item.field_id, item.repeatable_group_id): item
            for item in FormPrintFieldSettings.objects.filter(
                Q(field__section__form=form)
                | Q(repeatable_group__section__form=form)
            )
        }

        sections = []
        for section_context in dynamic_form.get("sections", []):
            section = section_context["section"]
            section_setting = section_settings.get(section.pk)
            if section_setting and not section_setting.is_enabled:
                continue

            items = []
            for field_context in section_context.get("fields", []):
                field = field_context["field"]
                setting = field_settings.get((field.pk, None))
                if setting and not setting.is_enabled:
                    continue
                item = cls._field_item(
                    field_context,
                    setting=setting,
                    show_empty_values=show_empty_values,
                )
                if item is not None:
                    item["sort_order"] = (
                        setting.print_order if setting else field.order
                    )
                    items.append(item)

            for group_context in section_context.get("repeatable_groups", []):
                group = group_context["group"]
                group_setting = field_settings.get((None, group.pk))
                if group_setting and not group_setting.is_enabled:
                    continue
                item = cls._group_item(
                    group_context,
                    setting=group_setting,
                    field_settings=field_settings,
                    show_empty_values=show_empty_values,
                )
                if item is not None:
                    item["sort_order"] = (
                        group_setting.print_order
                        if group_setting
                        else group.order
                    )
                    items.append(item)

            if not items:
                continue

            items.sort(key=lambda item: (item["sort_order"], item["label"].casefold()))
            sections.append({
                "title": (
                    section_setting.title_override
                    if section_setting and section_setting.title_override
                    else section.name
                ),
                "items": items,
                "sort_order": (
                    section_setting.print_order
                    if section_setting
                    else section.order
                ),
            })

        sections.sort(key=lambda item: (item["sort_order"], item["title"].casefold()))

        return {
            "title": (
                settings.document_title
                if settings and settings.document_title
                else form.name
            ),
            "subtitle": settings.subtitle if settings else "",
            "header_text": settings.header_text if settings else "",
            "footer_text": settings.footer_text if settings else "",
            "page_size": settings.page_size if settings else "A4",
            "orientation": settings.orientation if settings else "PORTRAIT",
            "show_workflow_name": settings.show_workflow_name if settings else True,
            "show_instance_number": settings.show_instance_number if settings else True,
            "show_created_at": settings.show_created_at if settings else True,
            "show_signatures": settings.show_signatures if settings else False,
            "signature_count": settings.signature_count if settings else 2,
            "workflow_name": (
                instance.workflow.name
                if settings is None or settings.show_workflow_name
                else None
            ),
            "instance_number": (
                instance.pk
                if settings is None or settings.show_instance_number
                else None
            ),
            "created_at": (
                instance.started_at
                if settings is None or settings.show_created_at
                else None
            ),
            "sections": sections,
        }

    @staticmethod
    def _field_item(field_context, *, setting, show_empty_values):
        field = field_context["field"]
        value = field_context.get("display_value", field_context.get("value", ""))
        if value in (None, "") and not show_empty_values:
            return None
        return {
            "type": "field",
            "label": (
                setting.title_override
                if setting and setting.title_override
                else field.label
            ),
            "value": value if value is not None else "",
        }

    @classmethod
    def _group_item(
        cls,
        group_context,
        *,
        setting,
        field_settings,
        show_empty_values,
    ):
        group = group_context["group"]
        row_contexts = group_context.get("items", [])

        # A group's header field contexts usually contain metadata only;
        # actual values are attached to each row. Collect the visible field
        # definitions first, then retain columns with at least one value
        # unless the administrator asked to print empty values as well.
        field_contexts_by_id = {}
        for field_context in group_context.get("fields", []):
            field = field_context["field"]
            field_setting = field_settings.get((field.pk, None))
            if field_setting and not field_setting.is_enabled:
                continue
            field_contexts_by_id[field.pk] = field_context

        row_field_contexts = []
        for row in row_contexts:
            by_id = {}
            for field_context in row.get("fields", []):
                field = field_context["field"]
                field_setting = field_settings.get((field.pk, None))
                if field_setting and not field_setting.is_enabled:
                    continue
                field_contexts_by_id.setdefault(field.pk, field_context)
                by_id[field.pk] = field_context
            row_field_contexts.append(by_id)

        def has_value(context):
            value = context.get("display_value", context.get("value", ""))
            return value not in (None, "", [], ())

        columns = []
        for field_id, field_context in field_contexts_by_id.items():
            if not show_empty_values and not any(
                has_value(row_fields[field_id])
                for row_fields in row_field_contexts
                if field_id in row_fields
            ):
                continue
            field = field_context["field"]
            field_setting = field_settings.get((field.pk, None))
            columns.append({
                "field_id": field.pk,
                "label": (
                    field_setting.title_override
                    if field_setting and field_setting.title_override
                    else field.label
                ),
            })

        rows = []
        for row, row_fields in zip(row_contexts, row_field_contexts):
            values = []
            for column in columns:
                context = row_fields.get(column["field_id"], {})
                value = context.get(
                    "display_value",
                    context.get("value", ""),
                )
                values.append({
                    "label": column["label"],
                    "value": value if value is not None else "",
                })

            child_groups = []
            for child_context in row.get("child_groups", []):
                child_group = child_context["group"]
                child_setting = field_settings.get((None, child_group.pk))
                if child_setting and not child_setting.is_enabled:
                    continue
                child_item = cls._group_item(
                    child_context,
                    setting=child_setting,
                    field_settings=field_settings,
                    show_empty_values=show_empty_values,
                )
                if child_item is not None:
                    child_groups.append(child_item)

            row_has_value = any(
                item["value"] not in (None, "", [], ())
                for item in values
            )
            if row_has_value or child_groups or show_empty_values:
                rows.append({
                    "fields": values,
                    "child_groups": child_groups,
                })

        if not columns and not rows:
            return None

        return {
            "type": "group",
            "label": (
                setting.title_override
                if setting and setting.title_override
                else (group.label or group.name)
            ),
            "layout": (
                setting.group_layout
                if setting
                else FormPrintFieldSettings.GroupLayout.TABLE
            ),
            "columns": [item["label"] for item in columns],
            "rows": rows,
        }
