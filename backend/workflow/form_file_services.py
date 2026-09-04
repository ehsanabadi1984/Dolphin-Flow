import os
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.urls import reverse

from .form_file_models import FormFile
from .form_services import DynamicFormService
from .models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    RepeatableGroupAccess,
    WorkflowPermission,
)


MAX_FILE_SIZE = 10 * 1024 * 1024


def is_file_field(field):
    return field.field_type == "FILE"


def _current_form(instance):
    return (
        FormDefinition.objects
        .filter(
            workflow=instance.workflow,
            is_active=True,
        )
        .prefetch_related(
            "sections__fields__access_rules",
            "sections__repeatable_groups__fields__access_rules",
        )
        .first()
    )


def prepare_submitted_data_for_files(*, instance, submitted_data, submitted_files):
    """
    Add empty POST placeholders for repeatable rows that contain a file.

    File inputs are sent through request.FILES and therefore do not appear
    in request.POST. DynamicFormService discovers repeatable rows from POST
    keys, so a file-only row needs a placeholder key to survive parsing.
    """
    post_data = submitted_data.copy()
    form = _current_form(instance)
    if form is None:
        return post_data

    normal_group_fields = (
        FormField.objects
        .filter(
            section__form=form,
            is_active=True,
            field_type="FILE",
            repeatable_group__group_type=FormRepeatableGroup.GroupType.NORMAL,
        )
        .select_related("repeatable_group")
    )

    for field in normal_group_fields:
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
        size_mb = MAX_FILE_SIZE // (1024 * 1024)
        return f"حجم فایل «{field.label}» نباید بیشتر از {size_mb} مگابایت باشد."

    return None


def _field_can_edit(field, *, user, step):
    rules = field.access_rules.filter(step=step)
    user_rule = rules.filter(user=user).first()
    if user_rule:
        return bool(user_rule.can_edit)

    roles = set(
        field.section.form.workflow.memberships
        .filter(user=user, is_active=True)
        .values_list("role", flat=True)
    )
    return rules.filter(
        role__in=roles,
        user__isnull=True,
        can_edit=True,
    ).exists()


def _group_can_edit(group, *, user, step):
    rules = group.access_rules.filter(step=step)
    user_rule = rules.filter(user=user).first()
    if user_rule:
        return bool(user_rule.can_edit)

    roles = set(
        group.section.form.workflow.memberships
        .filter(user=user, is_active=True)
        .values_list("role", flat=True)
    )
    return rules.filter(
        role__in=roles,
        user__isnull=True,
        can_edit=True,
    ).exists()


def validate_uploaded_files(*, instance, user, submitted_data, submitted_files):
    """Validate FILE fields before DynamicFormService writes form data."""
    if instance.current_step_id is None:
        return

    form = _current_form(instance)
    if form is None:
        return

    form_data = FormData.objects.filter(instance=instance).first()
    existing = {}
    if form_data:
        for item in FormFile.objects.filter(form_data=form_data):
            existing[(item.field_id, item.row_id)] = item

    errors = []
    step = instance.current_step

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
                continue

            if (
                field.is_required
                and not _upload_present(upload)
                and (field.pk, "") not in existing
            ):
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

            file_fields = list(
                group.fields.filter(
                    is_active=True,
                    field_type="FILE",
                )
            )

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
                        continue

                    if (
                        field.is_required
                        and not _upload_present(upload)
                        and (field.pk, row_id) not in existing
                    ):
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
        .filter(
            form_data=form_data,
            field=field,
            row_id=row_id,
        )
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
            "file",
            "original_name",
            "file_size",
            "content_type",
            "uploaded_by",
            "updated_at",
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
            file_fields = list(group.fields.filter(
                is_active=True,
                field_type="FILE",
            ))
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
                    key = f"{group.code}_{index}_{field.code}"
                    _replace_file(
                        form_data=form_data,
                        field=field,
                        row_id=row_id,
                        upload=submitted_files.get(key),
                        user=user,
                    )


def attach_files_to_form_context(*, instance, form_context):
    """Attach existing FormFile objects to the normal operator-form context."""
    if not form_context:
        return form_context

    form_data = FormData.objects.filter(instance=instance).first()
    if form_data is None:
        return form_context

    files = {
        (item.field_id, item.row_id): item
        for item in FormFile.objects.filter(form_data=form_data)
    }

    for section in form_context.get("sections", []):
        for item in section.get("fields", []):
            field = item["field"]
            if is_file_field(field):
                item["file"] = files.get((field.pk, ""))
                if item.get("file"):
                    item["file_url"] = reverse(
                        "operator_panel:download_form_file",
                        args=[item["file"].pk],
                    )

        for group in section.get("repeatable_groups", []):
            if group["group"].group_type != FormRepeatableGroup.GroupType.NORMAL:
                continue
            for item in group.get("items", []):
                row_id = str(item.get("row_id", "") or "")
                for item_field in item.get("fields", []):
                    field = item_field["field"]
                    if is_file_field(field):
                        item_field["file"] = files.get((field.pk, row_id))
                        if item_field.get("file"):
                            item_field["file_url"] = reverse(
                                "operator_panel:download_form_file",
                                args=[item_field["file"].pk],
                            )

    return form_context


def delete_form_files(*, instance):
    form_data = FormData.objects.filter(instance=instance).first()
    if form_data is None:
        return

    for item in FormFile.objects.filter(form_data=form_data):
        if item.file:
            item.file.delete(save=False)
        item.delete()


def _can_view_file(*, form_file, user):
    field = form_file.field
    instance = form_file.form_data.instance
    step = instance.current_step

    if user.is_superuser:
        return True

    if step is None:
        return False

    field_rules = field.access_rules.filter(step=step)
    user_rule = field_rules.filter(user=user).first()
    if user_rule:
        field_allowed = user_rule.can_view
    else:
        roles = set(
            instance.workflow.memberships
            .filter(user=user, is_active=True)
            .values_list("role", flat=True)
        )
        field_allowed = field_rules.filter(
            role__in=roles,
            user__isnull=True,
            can_view=True,
        ).exists()

    if not field_allowed:
        return False

    if field.repeatable_group_id:
        group = field.repeatable_group
        group_rules = group.access_rules.filter(step=step)
        user_group_rule = group_rules.filter(user=user).first()
        if user_group_rule:
            return bool(user_group_rule.can_view)
        roles = set(
            instance.workflow.memberships
            .filter(user=user, is_active=True)
            .values_list("role", flat=True)
        )
        return group_rules.filter(
            role__in=roles,
            user__isnull=True,
            can_view=True,
        ).exists()

    return True


def open_form_file(*, file_id, user):
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
    if form_file is None or not _can_view_file(form_file=form_file, user=user):
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
