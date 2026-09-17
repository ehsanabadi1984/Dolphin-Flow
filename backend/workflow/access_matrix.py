from django.db import transaction

from .history_permissions import HISTORY_ACTION
from .models import (
    FieldAccess,
    FormField,
    FormRepeatableGroup,
    RepeatableGroupAccess,
    WorkflowPermission,
    WorkflowTransition,
)


WORKFLOW_ACTIONS = (
    (WorkflowPermission.Action.VIEW, "مشاهده"),
    (WorkflowPermission.Action.START, "شروع فرآیند"),
    (WorkflowPermission.Action.MANAGE, "مدیریت"),
    (HISTORY_ACTION, "سوابق"),
)

STEP_ACTIONS = (
    (WorkflowPermission.Action.VIEW, "مشاهده"),
    (WorkflowPermission.Action.EXECUTE, "اجرا"),
    (WorkflowPermission.Action.MANAGE, "مدیریت"),
)


def _subject_kwargs(subject_type, subject_value):
    if subject_type == "user":
        return {"user_id": int(subject_value), "role": None}
    return {"user": None, "role": subject_value}


def _permission_scope_qs(workflow, subject_type, subject_value):
    if subject_type == "user":
        return WorkflowPermission.objects.filter(workflow=workflow, user_id=int(subject_value))
    return WorkflowPermission.objects.filter(workflow=workflow, user__isnull=True, role=subject_value)


def _set_permission(workflow, subject_type, subject_value, *, action, step=None, transition=None, enabled=False):
    qs = _permission_scope_qs(workflow, subject_type, subject_value).filter(
        action=action,
        step=step,
        transition=transition,
    )
    if enabled:
        obj = qs.order_by("pk").first()
        if obj is None:
            WorkflowPermission.objects.create(
                workflow=workflow,
                action=action,
                effect=WorkflowPermission.Effect.ALLOW,
                step=step,
                transition=transition,
                **_subject_kwargs(subject_type, subject_value),
            )
        else:
            obj.effect = WorkflowPermission.Effect.ALLOW
            if subject_type == "user" and obj.role_id is not None:
                obj.role = None
                obj.save(update_fields=["effect", "role", "updated_at"])
            else:
                obj.save(update_fields=["effect", "updated_at"])
            qs.exclude(pk=obj.pk).delete()
    else:
        qs.delete()


def _access_scope_qs(model, subject_type, subject_value, **filters):
    if subject_type == "user":
        return model.objects.filter(user_id=int(subject_value), **filters)
    return model.objects.filter(user__isnull=True, role=subject_value, **filters)


def _set_field_access(subject_type, subject_value, step, field, *, can_view, can_edit):
    qs = _access_scope_qs(FieldAccess, subject_type, subject_value, field=field, step=step)
    if not can_view and not can_edit:
        qs.delete()
        return

    obj = qs.order_by("pk").first()
    if obj is None:
        FieldAccess.objects.create(field=field, step=step, can_view=can_view, can_edit=can_edit, **_subject_kwargs(subject_type, subject_value))
    else:
        obj.can_view = can_view
        obj.can_edit = can_edit
        update_fields = ["can_view", "can_edit"]
        if subject_type == "user" and obj.role_id is not None:
            obj.role = None
            update_fields.append("role")
        obj.save(update_fields=update_fields)
        qs.exclude(pk=obj.pk).delete()


def _set_group_access(subject_type, subject_value, step, group, *, can_view, can_edit, can_add, can_delete):
    qs = _access_scope_qs(RepeatableGroupAccess, subject_type, subject_value, group=group, step=step)
    if not can_view and not can_edit and not can_add and not can_delete:
        qs.delete()
        return

    obj = qs.order_by("pk").first()
    if obj is None:
        RepeatableGroupAccess.objects.create(
            group=group,
            step=step,
            can_view=can_view,
            can_edit=can_edit,
            can_add=can_add,
            can_delete=can_delete,
            **_subject_kwargs(subject_type, subject_value),
        )
    else:
        obj.can_view = can_view
        obj.can_edit = can_edit
        obj.can_add = can_add
        obj.can_delete = can_delete
        update_fields = ["can_view", "can_edit", "can_add", "can_delete"]
        if subject_type == "user" and obj.role_id is not None:
            obj.role = None
            update_fields.append("role")
        obj.save(update_fields=update_fields)
        qs.exclude(pk=obj.pk).delete()


@transaction.atomic
def save_access_matrix(*, workflow, subject_type, subject_value, step, post_data):
    if subject_type not in {"user", "role"}:
        raise ValueError("نوع Subject نامعتبر است.")
    if subject_type == "user":
        int(subject_value)
    if step.workflow_id != workflow.pk:
        raise ValueError("مرحله انتخاب‌شده متعلق به این Workflow نیست.")

    for action, _label in WORKFLOW_ACTIONS:
        _set_permission(workflow, subject_type, subject_value, action=action, enabled=post_data.get(f"workflow_{action}") == "1")

    for action, _label in STEP_ACTIONS:
        _set_permission(workflow, subject_type, subject_value, action=action, step=step, enabled=post_data.get(f"step_{action}") == "1")

    transitions = WorkflowTransition.objects.filter(workflow=workflow, from_step=step, is_active=True)
    for transition in transitions:
        _set_permission(
            workflow,
            subject_type,
            subject_value,
            action=WorkflowPermission.Action.TRANSITION,
            transition=transition,
            enabled=post_data.get(f"transition_{transition.pk}") == "1",
        )

    fields = FormField.objects.filter(section__form__workflow=workflow, is_active=True)
    for field in fields:
        _set_field_access(
            subject_type,
            subject_value,
            step,
            field,
            can_view=post_data.get(f"field_{field.pk}_view") == "1",
            can_edit=post_data.get(f"field_{field.pk}_edit") == "1",
        )

    groups = FormRepeatableGroup.objects.filter(section__form__workflow=workflow, is_active=True)
    for group in groups:
        _set_group_access(
            subject_type,
            subject_value,
            step,
            group,
            can_view=post_data.get(f"group_{group.pk}_view") == "1",
            can_edit=post_data.get(f"group_{group.pk}_edit") == "1",
            can_add=post_data.get(f"group_{group.pk}_add") == "1",
            can_delete=post_data.get(f"group_{group.pk}_delete") == "1",
        )
