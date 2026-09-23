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
from .models import RepeatableRow
from .permission_context import PermissionContext
from .form_draft_diff_services import RowReference, RowReferenceKind
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
        
        .first()
    )


def prepare_submitted_data_for_files(*, instance, submitted_data, submitted_files):
    """Make FILE-only repeatable rows visible to the normal form parser."""
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


def validate_uploaded_files(*, instance, user, submitted_data, submitted_files):
    """Validate FILE fields before DynamicFormService persists normal form data."""
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
    permission_context = PermissionContext.build(workflow=instance.workflow, form=form, step=step, user=user)
    errors = []

    for section in form.sections.filter(is_active=True):
        for field in section.fields.filter(
            is_active=True,
            repeatable_group__isnull=True,
            field_type="FILE",
        ):
            upload = submitted_files.get(field.code)
            if not permission_context.field(field).can_edit:
                if _upload_present(upload):
                    errors.append({
                        "type": "field",
                        "code": field.code,
                        "label": field.label,
                        "message": f"شما اجازه ویرایش فایل «{field.label}» را ندارید.",
                    })
                continue
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
            group_can_edit = permission_context.group(group).can_edit
            rows = DynamicFormService._parse_repeatable_data(
                submitted_data=submitted_data,
                group_code=group.code,
            )
            file_fields = list(group.fields.filter(is_active=True, field_type="FILE"))
            persisted_row_ids = set(
                str(row_id)
                for row_id in RepeatableRow.objects.filter(
                    instance=instance,
                    group=group,
                ).values_list("pk", flat=True)
            )
            for index, row in enumerate(rows):
                submitted_row_id = str(row.get("_id", "") or "")
                row_id = (
                    submitted_row_id
                    if submitted_row_id in persisted_row_ids
                    else ""
                )
                for field in file_fields:
                    key = f"{group.code}_{index}_{field.code}"
                    upload = submitted_files.get(key)
                    if not group_can_edit or not permission_context.field(field).can_edit:
                        if _upload_present(upload):
                            errors.append({
                                "type": "repeatable_field",
                                "group_code": group.code,
                                "field_code": field.code,
                                "item_index": index,
                                "message": f"شما اجازه ویرایش فایل «{field.label}» را ندارید.",
                            })
                        continue
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


def _normalized_row_id(*, normalized_row, group, save_result, parent_reference=None):
    if normalized_row.row_id is not None:
        return str(normalized_row.row_id)

    for group_diff in save_result.diff.groups:
        for change in group_diff.changes:
            if change.group.pk != group.pk:
                continue
            if change.action.value != "create":
                continue
            if change.parent_reference != parent_reference:
                continue
            if change.desired_row is not normalized_row:
                continue
            row = save_result.created_rows.get(change.row_reference)
            if row is not None:
                return str(row.pk)
            return None

    return None


def _normalized_row_reference(*, normalized_row, group, save_result, parent_reference=None):
    if normalized_row.row_id is not None:
        return RowReference(
            kind=RowReferenceKind.EXISTING,
            value=normalized_row.row_id,
        )

    for group_diff in save_result.diff.groups:
        for change in group_diff.changes:
            if change.group.pk != group.pk:
                continue
            if change.action.value != "create":
                continue
            if change.parent_reference != parent_reference:
                continue
            if change.desired_row is not normalized_row:
                continue
            return change.row_reference

    return None


def _save_repeatable_group_files(
    *,
    form_data,
    group,
    normalized_rows,
    submitted_files,
    user,
    save_result,
    group_prefix=None,
    parent_reference=None,
):
    file_fields = list(group.fields.filter(is_active=True, field_type="FILE"))
    if not file_fields:
        return

    prefix = group_prefix or f"{group.code}_"

    for index, normalized_row in enumerate(normalized_rows):
        row_id = _normalized_row_id(
            normalized_row=normalized_row,
            group=group,
            save_result=save_result,
            parent_reference=parent_reference,
        )
        row_reference = _normalized_row_reference(
            normalized_row=normalized_row,
            group=group,
            save_result=save_result,
            parent_reference=parent_reference,
        )
        if not row_id:
            continue

        for field in file_fields:
            _replace_file(
                form_data=form_data,
                field=field,
                row_id=row_id,
                upload=submitted_files.get(
                    f"{prefix}{index}_{field.code}"
                ),
                user=user,
            )

        for child_group_code, child_rows in normalized_row.child_groups.items():
            child_group = group.child_groups.filter(
                code=child_group_code,
                is_active=True,
            ).first()
            if child_group is None:
                continue
            _save_repeatable_group_files(
                form_data=form_data,
                group=child_group,
                normalized_rows=child_rows,
                submitted_files=submitted_files,
                user=user,
                save_result=save_result,
                group_prefix=f"{prefix}{index}_{child_group.code}_",
                parent_reference=row_reference,
            )


@transaction.atomic
def save_uploaded_form_files(*, instance, user, submitted_files, save_result=None):
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

        if save_result is None:
            continue

        for group in section.repeatable_groups.filter(
            is_active=True,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            parent_group__isnull=True,
        ):
            normalized_rows = save_result.normalized_payload.repeatable_groups.get(
                group.code,
                (),
            )
            _save_repeatable_group_files(
                form_data=form_data,
                group=group,
                normalized_rows=normalized_rows,
                submitted_files=submitted_files,
                user=user,
                save_result=save_result,
            )


def _file_payload(item):
    return {
        "id": item.pk,
        "name": item.original_name or Path(item.file.name).name,
        "url": reverse("operator_panel:download_form_file", args=[item.pk]),
        "delete_url": reverse("operator_panel:delete_form_file", args=[item.pk]),
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

    step = instance.current_step
    permission_context = PermissionContext.build(workflow=instance.workflow, form=form, step=step, user=request.user)

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
            if not permission_context.field(field).can_view:
                continue
            fields.append({
                "field_id": field.pk,
                "code": field.code,
                "label": field.label,
                "scope": "FORM",
                "editable": permission_context.field(field).can_edit,
                "required": bool(field.is_required),
                "input_name": field.code,
                "file": existing.get((field.pk, "")),
            })

        for group in section.repeatable_groups.filter(
            is_active=True,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
        ):
            if not permission_context.group(group).can_view:
                continue

            visible_fields = [
                field
                for field in group.fields.filter(is_active=True)
                if permission_context.field(field).can_view
            ]
            group_fields = []
            field_ids = set()

            for column_index, field in enumerate(visible_fields):
                if field.field_type != "FILE":
                    continue
                field_ids.add(field.pk)
                group_fields.append({
                    "field_id": field.pk,
                    "code": field.code,
                    "label": field.label,
                    "editable": (
                        permission_context.field(field).can_edit
                        and permission_context.group(group).can_edit
                    ),
                    "required": bool(field.is_required),
                    "column_index": column_index,
                })

            if not group_fields:
                continue

            file_payloads = []
            row_indexes = {
                str(row.pk): index
                for index, row in enumerate(
                    RepeatableRow.objects.filter(
                        instance=instance,
                        group=group,
                        parent_row__isnull=True,
                    ).order_by("row_order", "pk")
                )
            }
            for (field_id, row_id), payload in existing.items():
                if field_id in field_ids:
                    field_code = next(
                        item["code"] for item in group_fields if item["field_id"] == field_id
                    )
                    file_payloads.append({
                        "field_code": field_code,
                        "row_id": row_id,
                        "row_index": row_indexes.get(str(row_id), -1),
                        **payload,
                    })

            groups.append({
                "code": group.code,
                "fields": group_fields,
                "files": file_payloads,
                "is_table": group.display_type == "TABLE",
            })

    return JsonResponse({"fields": fields, "groups": groups})


@login_required
@transaction.atomic
def delete_form_file(request, file_id):
    if request.method != "POST":
        return JsonResponse({"error": "فقط درخواست POST مجاز است."}, status=405)

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
    step = instance.current_step

    WorkflowAuthorizationService.require_permission(
        user=request.user,
        workflow=instance.workflow,
        action=WorkflowPermission.Action.VIEW,
        step=step,
        instance=instance,
    )

    form = _current_form(instance)
    if form is None:
        raise Http404
    permission_context = PermissionContext.build(workflow=instance.workflow, form=form, step=step, user=request.user)

    if not permission_context.field(form_file.field).can_edit:
        return JsonResponse({"error": "شما اجازه حذف این فایل را ندارید."}, status=403)

    if form_file.field.repeatable_group_id and not permission_context.group(form_file.field.repeatable_group).can_edit:
        return JsonResponse({"error": "شما اجازه حذف این فایل را ندارید."}, status=403)

    if form_file.file:
        form_file.file.delete(save=False)
    form_file.delete()

    return JsonResponse({"success": True, "file_id": file_id})


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
    result = views.workflow_instance(
        request,
        instance_id,
        _return_save_result=True,
    )
    if isinstance(result, tuple):
        response, save_result = result
    else:
        response, save_result = result, None
    if 300 <= response.status_code < 400:
        save_uploaded_form_files(
            instance=instance,
            user=request.user,
            submitted_files=request.FILES,
            save_result=save_result,
        )
    return response


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

    form = _current_form(instance)
    if form is None:
        raise Http404
    permission_context = PermissionContext.build(workflow=instance.workflow, form=form, step=instance.current_step, user=request.user)

    if not permission_context.field(form_file.field).can_view:
        raise Http404

    if form_file.field.repeatable_group_id and not permission_context.group(form_file.field.repeatable_group).can_view:
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
