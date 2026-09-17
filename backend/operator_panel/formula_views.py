from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from workflow.authorization import WorkflowAuthorizationService
from workflow.formula_services import FormulaService
from workflow.models import (
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    WorkflowInstance,
    WorkflowPermission,
)


def _field_access(field, *, user, step):
    if user.is_superuser:
        return True

    roles = set(
        field.section.form.workflow.memberships
        .filter(user=user, is_active=True)
        .values_list("role", flat=True)
    )
    rules = field.access_rules.filter(step=step)
    user_rule = rules.filter(user=user).first()
    if user_rule:
        return user_rule.can_view
    return rules.filter(
        role__in=roles,
        user__isnull=True,
        can_view=True,
    ).exists()


def _group_access(group, *, user, step):
    if user.is_superuser:
        return True

    roles = set(
        group.section.form.workflow.memberships
        .filter(user=user, is_active=True)
        .values_list("role", flat=True)
    )
    rules = group.access_rules.filter(step=step)
    user_rule = rules.filter(user=user).first()
    if user_rule:
        return user_rule.can_view
    return rules.filter(
        role__in=roles,
        user__isnull=True,
        can_view=True,
    ).exists()


def _formula_source_fields(*, section_id, group_id, exclude_id=None):
    if not section_id:
        return FormField.objects.none()

    section = get_object_or_404(
        FormSection.objects.select_related("form"),
        pk=section_id,
    )

    queryset = (
        FormField.objects
        .filter(
            section__form=section.form,
            is_active=True,
            field_type__in=[
                FormField.FieldType.NUMBER,
                FormulaService.FIELD_TYPE,
            ],
        )
        .select_related("repeatable_group", "section")
        .order_by(
            "section__order",
            "repeatable_group__order",
            "repeatable_group_id",
            "order",
            "id",
        )
    )

    if exclude_id:
        queryset = queryset.exclude(pk=exclude_id)

    if group_id:
        group = get_object_or_404(
            FormRepeatableGroup,
            pk=group_id,
            section__form=section.form,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
        )
        return queryset.filter(repeatable_group=group)

    return queryset


@staff_member_required
def formula_field_options(request):
    try:
        section_id = int(request.GET.get("section_id", ""))
    except (TypeError, ValueError):
        section_id = None

    try:
        group_id = int(request.GET.get("group_id", "")) if request.GET.get("group_id") else None
    except (TypeError, ValueError):
        group_id = None

    try:
        exclude_id = int(request.GET.get("exclude_id", "")) if request.GET.get("exclude_id") else None
    except (TypeError, ValueError):
        exclude_id = None

    fields = [
        {
            "id": field.pk,
            "code": field.code,
            "label": field.label,
            "section_order": field.section.order,
            "section_id": field.section_id,
            "section_label": field.section.name,
            "group_code": field.repeatable_group.code if field.repeatable_group_id else None,
            "group_label": field.repeatable_group.name if field.repeatable_group_id else None,
            "is_group_field": field.repeatable_group_id is not None,
        }
        for field in _formula_source_fields(
            section_id=section_id,
            group_id=group_id,
            exclude_id=exclude_id,
        )
    ]
    return JsonResponse({"fields": fields})


@login_required
def formula_definitions(request, instance_id):
    instance = get_object_or_404(
        WorkflowInstance.objects.select_related(
            "workflow",
            "current_step",
        ),
        pk=instance_id,
    )

    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
        instance=instance,
    )

    form = (
        FormDefinition.objects
        .filter(workflow=instance.workflow, is_active=True)
        .first()
    )
    if form is None or instance.current_step_id is None:
        return JsonResponse(
            {
                "form_id": form.pk if form else None,
                "fields": [],
                "formulas": [],
                "source_data": {},
            }
        )

    form_data = FormData.objects.filter(instance=instance).first()
    stored_data = form_data.data if form_data and isinstance(form_data.data, dict) else {}

    all_fields = list(
        FormField.objects
        .filter(section__form=form, is_active=True)
        .select_related("section", "repeatable_group")
        .order_by("section__order", "repeatable_group__order", "order", "id")
    )

    visible_fields = []
    visible_field_ids = set()
    normal_dom_index = 0
    group_visible_columns = {}

    for field in all_fields:
        if field.repeatable_group_id:
            group = field.repeatable_group
            if group.group_type != FormRepeatableGroup.GroupType.NORMAL:
                continue
            if not _group_access(group, user=request.user, step=instance.current_step):
                continue
        else:
            if _field_access(field, user=request.user, step=instance.current_step):
                field_dom_index = normal_dom_index
                normal_dom_index += 1
            else:
                continue

        if not _field_access(field, user=request.user, step=instance.current_step):
            continue

        if field.repeatable_group_id:
            group_visible_columns.setdefault(field.repeatable_group_id, []).append(field.code)

        if field.field_type not in {
            FormField.FieldType.NUMBER,
            FormulaService.FIELD_TYPE,
        }:
            continue

        field_payload = {
            "id": field.pk,
            "code": field.code,
            "label": field.label,
            "group_code": (
                field.repeatable_group.code
                if field.repeatable_group_id
                else None
            ),
        }

        if field.repeatable_group_id is None:
            field_payload["dom_index"] = field_dom_index

        visible_field_ids.add(field.pk)
        visible_fields.append(field_payload)

    all_formula_fields = [
        field for field in all_fields
        if field.field_type == FormulaService.FIELD_TYPE
    ]

    formulas = []
    formula_configs = {}
    required_source_ids = set()

    for field in all_formula_fields:
        if field.pk not in visible_field_ids:
            continue

        config = FormulaService.get_config(field)
        if not config:
            continue

        formula_configs[field.pk] = config
        required_source_ids.update(FormulaService.referenced_field_ids(config))

        if field.repeatable_group_id:
            group = field.repeatable_group
            visible_columns = group_visible_columns.get(group.pk, [])
            scope = "ROW"
            group_code = group.code
        else:
            visible_columns = []
            scope = "FORM"
            group_code = None

        formulas.append(
            {
                "field_id": field.pk,
                "code": field.code,
                "label": field.label,
                "group_code": group_code,
                "scope": scope,
                "decimal_places": config.get("decimal_places", 2),
                "tokens": config.get("tokens", []),
                "visible_columns": visible_columns,
            }
        )

    # Include the dependency closure so a visible formula can resolve another
    # formula field even when that dependency is hidden in the current step.
    changed = True
    while changed:
        changed = False
        for field_id in list(required_source_ids):
            config = formula_configs.get(field_id)
            if config is None:
                field = next((item for item in all_formula_fields if item.pk == field_id), None)
                if field is None:
                    continue
                config = FormulaService.get_config(field)
                if not config:
                    continue
                formula_configs[field_id] = config
            before = len(required_source_ids)
            required_source_ids.update(FormulaService.referenced_field_ids(config))
            changed = changed or len(required_source_ids) != before

    # Hidden formula dependencies must be sent as formula definitions too.
    # They are used only by the calculation engine and are never rendered.
    visible_formula_ids = {item["field_id"] for item in formulas}
    for field_id, config in formula_configs.items():
        if field_id in visible_formula_ids:
            continue
        field = next((item for item in all_formula_fields if item.pk == field_id), None)
        if field is None:
            continue
        if field.repeatable_group_id:
            group = field.repeatable_group
            visible_columns = group_visible_columns.get(group.pk, [])
            scope = "ROW"
            group_code = group.code
        else:
            visible_columns = []
            scope = "FORM"
            group_code = None
        formulas.append(
            {
                "field_id": field.pk,
                "code": field.code,
                "label": field.label,
                "group_code": group_code,
                "scope": scope,
                "decimal_places": config.get("decimal_places", 2),
                "tokens": config.get("tokens", []),
                "visible_columns": visible_columns,
                "calculation_only": True,
            }
        )

    # Formula resolution must know every numeric/formula source field even
    # when the current workflow step hides that field. These entries are used
    # only by the calculation engine; they are not rendered by this endpoint.
    for field in all_fields:
        if field.pk in visible_field_ids:
            continue
        if field.pk not in required_source_ids:
            continue
        if field.field_type not in {
            FormField.FieldType.NUMBER,
            FormulaService.FIELD_TYPE,
        }:
            continue
        visible_fields.append(
            {
                "id": field.pk,
                "code": field.code,
                "label": field.label,
                "group_code": (
                    field.repeatable_group.code
                    if field.repeatable_group_id
                    else None
                ),
            }
        )

    source_data = {}
    for field in all_fields:
        if field.pk not in required_source_ids:
            continue
        if field.repeatable_group_id:
            group = field.repeatable_group
            rows = stored_data.get(group.code, [])
            source_data[str(field.pk)] = {
                "code": field.code,
                "group_code": group.code,
                "value": rows if isinstance(rows, list) else [],
            }
        else:
            source_data[str(field.pk)] = {
                "code": field.code,
                "group_code": None,
                "value": stored_data.get(field.code, ""),
            }

    return JsonResponse(
        {
            "form_id": form.pk,
            "fields": visible_fields,
            "formulas": formulas,
            "source_data": source_data,
        }
    )
