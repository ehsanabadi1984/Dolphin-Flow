from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from workflow.authorization import WorkflowAuthorizationService
from workflow.formula_services import FormulaService
from workflow.models import (
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

    section = get_object_or_404(FormSection.objects.select_related("form"), pk=section_id)

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
        .select_related("repeatable_group")
        .order_by("repeatable_group_id", "order", "id")
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
        queryset = queryset.filter(repeatable_group=group)
    else:
        queryset = queryset.filter(repeatable_group__isnull=True)

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
            }
        )

    visible_fields = []
    visible_field_ids = set()

    for field in (
        FormField.objects
        .filter(section__form=form, is_active=True)
        .select_related("section", "repeatable_group")
        .order_by("section__order", "repeatable_group__order", "order", "id")
    ):
        if field.repeatable_group_id:
            group = field.repeatable_group
            if group.group_type != FormRepeatableGroup.GroupType.NORMAL:
                continue
            if not _group_access(group, user=request.user, step=instance.current_step):
                continue

        if not _field_access(field, user=request.user, step=instance.current_step):
            continue

        if field.field_type not in {
            FormField.FieldType.NUMBER,
            FormulaService.FIELD_TYPE,
        }:
            continue

        visible_field_ids.add(field.pk)
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

    formulas = []
    all_formula_fields = (
        FormField.objects
        .filter(
            section__form=form,
            field_type=FormulaService.FIELD_TYPE,
            is_active=True,
        )
        .select_related("repeatable_group")
    )

    for field in all_formula_fields:
        if field.pk not in visible_field_ids:
            continue

        config = FormulaService.get_config(field)
        if not config:
            continue

        if field.repeatable_group_id:
            group = field.repeatable_group
            visible_columns = [
                item["code"]
                for item in visible_fields
                if item["group_code"] == group.code
            ]
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

    return JsonResponse(
        {
            "form_id": form.pk,
            "fields": visible_fields,
            "formulas": formulas,
        }
    )
