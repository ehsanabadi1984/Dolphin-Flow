import os
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse

from .authorization import WorkflowAuthorizationService
from .form_file_models import FormFile
from .form_services import DynamicFormService
from .models import (
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    WorkflowInstance,
    WorkflowPermission,
)

MAX_FILE_SIZE = 10 * 1024 * 1024


def _current_form(instance):
    return (
        FormDefinition.objects
        .filter(workflow=instance.workflow, is_active=True)
        .prefetch_related(
            "sections__fields__access_rules",
            "sections__repeatable_groups__fields__access_rules",
        )
        .first()
    )


def prepare_submitted_data_for_files(*, instance, submitted_data, submitted_files):
    post_data = submitted_data.copy()
    form = _current_form(instance)
    if form is None:
        return post_data

    file_fields = (
        FormField.objects
        .filter(
            section__form=form,
            is_active=True,
            field_type="FILE",
            repeatable_group__group_type=FormRepeatableGroup.GroupType.NORMAL,
        )
        .select_related("repeatable_group")
    )

    for field in file_fields:
        prefix = f"{field.repeatable_group.code}_"
        suffix = f"_{field.code}"
        for key in submitted_files.keys():
            if key.startswith(prefix) and key.endswith(suffix) and key not in post_data:
                post_data[key] = ""
    return post_data


def _upload_present(upload):
    return bool(upload and getattr(upload, "name", ""))


def _validate_upload(upload, field):
    if not _upload_present(upload):
        return None
    if upload.size > MAX_FILE_SIZE:
        return f"حجم فایل «{field.label}» نباید بیشتر از {MAX_FILE_SIZE // (1024 * 1024)} مگابایت باشد."
    return None


def _roles_for_workflow(workflow, user):
    return set(
        workflow.memberships
        .filter(user=user, is_active=True)
        .values_list("role", flat=True)
    )


def _field_can_edit(field, *, user, step):
    rules = field.access_rules.filter(step=step)
    user_rule = rules.filter(user=user).first()
    if user_rule:
        return bool(user_rule.can_edit)
    return rules.filter(
        role__in=_roles_for_workflow(field.section.form.workflow, user),
        user__isnull=True,
        can_edit=True,
    ).exists()


def _field_can_view(field, *, user, step):
    if user.is_superuser:
        return True
    if step is None:
        return False
    rules = field.access_rules.filter(step=step)
    user_rule = rules.filter(user=user).first()
    if user_rule:
        return bool(user_rule.can_view)
    return rules.filter(
        role__in=_roles_for_workflow(field.section.form.workflow, user),
        user__isnull=True,
        can_view=True,
    ).exists()


def _group_can_edit(group, *, user, step):
    rules = group.access_rules.filter(step=step)
    user_rule = rules.filter(user=user).first()
    if user_rule:
        return bool(user_rule.can_edit)
    return rules.filter(
        role__in=_roles_for_workflow(group.section.form.workflow, user),
        user__isnull=True,
        can_edit=True,
    ).exists()


def _group_can_view(group, *, user, step):
    if user.is_superuser:
        return True
    if step is None:
        return False
    rules = group.access_rules.filter(step=step)
    user_rule = rules.filter(user=user).first()
    if user_rule:
        return bool(user_rule.can_view)
    return rules.filter(
        role__in=_roles_for_workflow(group.section.form.workflow, user),
        user__isnull=True,
        can_view=True,
    ).exists()


def validate_uploaded_files(*, instance, user, submitted_data, submitted_files):
    if instance.current_step_id is None:
        return

    form = _current_form(instance)
    if form is None:
        return

    form_data = FormData.objects.filter(instance=instance).first()
    existing = {}
    if form_data:
        existing = {
            (item.field_id, item.row_id): item
            for item in FormFile.objects.filter(form_data=form_data)
        }

    step = instance.current_step
    errors = []

    for section in form.sections.filter(is_active=True):
        for field in section.fields.filter(
            is_active=True,
            repeatable_group__isnull=True,
            field_type="FILE",
        ):
            if not _field_can_edit(field, user=user, step=step):
                continue
            upload = submitted_files.get(field.code)
            error = _validate_upload(upload, field)
            if error:
                errors.append({
                    "type": "field",
                    "code": field.code,
                    "label": field.label,
                    "message": error,
                })
            elif field.is_required and not _upload_present(upload) and (field.pk, "") not in existing:
                errors.append({
                    "type": "field",
                    "code": field.code,
                    "label": field.label,
                    "message": f"فایل «{field.label}» الزامی است.",
                })

        for group in section.repeatable_groups.filter(
            is_active=True,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
        ):
            if not _group_can_edit(group, user=user, step=step):
                continue
            rows = DynamicFormService._parse_repeatable_data(
                submitted_data=submitted_data,
                group_code=group.code,
            )
            file_fields = list(group.fields.filter(is_active=True, field_type="FILE"))
            for index, row in enumerate(rows):
                row_id = str(row.get("_id", "") or "")
                for field in file_fields:
                    if not _field_can_edit(field, user=user, step=step):
                        continue
                    key = f"{group.code}_{index}_{field.code}"
                    upload = submitted_files.get(key)
                    error = _validate_upload(upload, field)
                    if error:
                        errors.append({
                            "type": "repeatable_field",
                            "group_code": group.code,
                            "field_code": field.code,
                            "item_index": index,
                            "message": error,
                        })
                    elif field.is_required and not _upload_present(upload) and (field.pk, row_id) not in existing:
                        errors.append({
                            "type": "repeatable_field",
                            "group_code": group.code,
                            "field_code": field.code,
                            "item_index": index,
                            "message": f"فایل «{field.label}» در ردیف {index + 1} الزامی است.",
                        })

    if errors:
        exc = ValidationError("اطلاعات فایل‌ها کامل یا معتبر نیست.")
        exc.validation_errors = errors
        raise exc


def _replace_file(*, form_data, field, row_id, upload, user):
    if not _upload_present(upload):
        return

    old = (
        FormFile.objects
        .filter(form_data=form_data, field=field, row_id=row_id)
        .first()
    )
    if old:
        if old.file:
            old.file.delete(save=False)
        old.file = upload
        old.original_name = os.path.basename(upload.name)
        old.file_size = upload.size
        old.content_type = getattr(upload, "content_type", "") or ""
        old.uploaded_by = user
        old.save(update_fields=[
            "file", "original_name", "file_size", "content_type", "uploaded_by", "updated_at"
        ])
        return

    FormFile.objects.create(
        form_data=form_data,
        field=field,
        row_id=row_id,
        file=upload,
        original_name=os.path.basename(upload.name),
        file_size=upload.size,
        content_type=getattr(upload, "content_type", "") or "",
        uploaded_by=user,
    )


@transaction.atomic
def save_uploaded_form_files(*, instance, user, submitted_files):
    form_data = FormData.objects.filter(instance=instance).first()
    if form_data is None:
        return

    form = _current_form(instance)
    if form is None:
        return

    for section in form.sections.filter(is_active=True):
        for field in section.fields.filter(
            is_active=True,
            repeatable_group__isnull=True,
            field_type="FILE",
        ):
            _replace_file(
                form_data=form_data,
                field=field,
                row_id="",
                upload=submitted_files.get(field.code),
                user=user,
            )

        for group in section.repeatable_groups.filter(
            is_active=True,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
        ):
            file_fields = list(group.fields.filter(is_active=True, field_type="FILE"))
            if not file_fields:
                continue
            rows = form_data.data.get(group.code, []) if isinstance(form_data.data, dict) else []
            if not isinstance(rows, list):
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                row_id = str(row.get("_id", "") or "")
                if not row_id:
                    continue
                for field in file_fields:
                    _replace_file(
                        form_data=form_data,
                        field=field,
                        row_id=row_id,
                        upload=submitted_files.get(f"{group.code}_{index}_{field.code}"),
                        user=user,
                    )


def _file_payload(item):
    return {
        "id": item.pk,
        "name": item.original_name or Path(item.file.name).name,
        "url": reverse("operator_panel:download_form_file", args=[item.pk]),
    }


@login_required
def file_field_definitions(request, instance_id):
    instance = get_object_or_404(
        WorkflowInstance.objects.select_related("workflow", "current_step"),
        pk=instance_id,
    )
    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
        instance=instance,
    )

    form = _current_form(instance)
    if form is None or instance.current_step_id is None:
        return JsonResponse({"fields": [], "groups": []})

    form_data = FormData.objects.filter(instance=instance).first()
    existing = {}
    if form_data:
        existing = {
            (item.field_id, item.row_id): _file_payload(item)
            for item in FormFile.objects.filter(form_data=form_data)
        }

    fields = []
    groups = []
    step = instance.current_step

    for section in form.sections.filter(is_active=True):
        for field in section.fields.filter(
            is_active=True,
            repeatable_group__isnull=True,
            field_type="FILE",
        ):
            if not _field_can_view(field, user=request.user, step=step):
                continue
            fields.append({
                "field_id": field.pk,
                "code": field.code,
                "label": field.label,
                "scope": "FORM",
                "editable": _field_can_edit(field, user=request.user, step=step),
                "required": bool(field.is_required),
                "input_name": field.code,
                "file": existing.get((field.pk, "")),
            })

        for group in section.repeatable_groups.filter(
            is_active=True,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
        ):
            if not _group_can_view(group, user=request.user, step=step):
                continue

            all_fields = list(group.fields.filter(is_active=True))
            group_fields = []
            field_ids = set()

            for column_index, field in enumerate(all_fields):
                if field.field_type != "FILE":
                    continue
                if not _field_can_view(field, user=request.user, step=step):
                    continue
                field_ids.add(field.pk)
                group_fields.append({
                    "field_id": field.pk,
                    "code": field.code,
                    "label": field.label,
                    "editable": (
                        _field_can_edit(field, user=request.user, step=step)
                        and _group_can_edit(group, user=request.user, step=step)
                    ),
                    "required": bool(field.is_required),
                    "column_index": column_index,
                })

            if not group_fields:
                continue

            file_payloads = []
            for (field_id, row_id), payload in existing.items():
                if field_id in field_ids:
                    field_code = next(
                        item["code"] for item in group_fields if item["field_id"] == field_id
                    )
                    file_payloads.append({
                        "field_code": field_code,
                        "row_id": row_id,
                        **payload,
                    })

            groups.append({
                "code": group.code,
                "fields": group_fields,
                "files": file_payloads,
            })

    return JsonResponse({"fields": fields, "groups": groups})


@login_required
def workflow_instance_with_files(request, instance_id):
    from operator_panel import views

    if request.method != "POST":
        return views.workflow_instance(request, instance_id)

    instance = get_object_or_404(
        WorkflowInstance.objects.select_related("workflow", "current_step"),
        pk=instance_id,
    )
    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
        instance=instance,
    )

    submitted_data = prepare_submitted_data_for_files(
        instance=instance,
        submitted_data=request.POST,
        submitted_files=request.FILES,
    )
    validate_uploaded_files(
        instance=instance,
        user=request.user,
        submitted_data=submitted_data,
        submitted_files=request.FILES,
    )

    request._post = submitted_data
    response = views.workflow_instance(request, instance_id)
    if 300 <= response.status_code < 400:
        save_uploaded_form_files(
            instance=instance,
            user=request.user,
            submitted_files=request.FILES,
        )
    return response


@login_required
def clear_form_data_with_files(request, instance_id):
    from operator_panel import views

    response = views.clear_form_data(request, instance_id)
    if 300 <= response.status_code < 400 and request.method == "POST":
        instance = get_object_or_404(WorkflowInstance, pk=instance_id)
        delete_form_files(instance=instance)
    return response


def delete_form_files(*, instance):
    form_data = FormData.objects.filter(instance=instance).first()
    if form_data is None:
        return
    for item in FormFile.objects.filter(form_data=form_data):
        if item.file:
            item.file.delete(save=False)
        item.delete()


@login_required
def open_form_file(request, file_id):
    form_file = (
        FormFile.objects
        .select_related(
            "form_data",
            "form_data__instance",
            "form_data__instance__workflow",
            "form_data__instance__current_step",
            "field",
            "field__section",
            "field__repeatable_group",
        )
        .filter(pk=file_id)
        .first()
    )
    if form_file is None:
        raise Http404

    instance = form_file.form_data.instance
    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=instance.current_step,
        instance=instance,
    )

    if not _field_can_view(form_file.field, user=request.user, step=instance.current_step):
        raise Http404

    if form_file.field.repeatable_group_id and not _group_can_view(
        form_file.field.repeatable_group,
        user=request.user,
        step=instance.current_step,
    ):
        raise Http404

    try:
        form_file.file.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404

    filename = form_file.original_name or Path(form_file.file.name).name
    response = FileResponse(
        form_file.file,
        as_attachment=True,
        filename=filename,
    )
    if form_file.content_type:
        response["Content-Type"] = form_file.content_type
    return response
