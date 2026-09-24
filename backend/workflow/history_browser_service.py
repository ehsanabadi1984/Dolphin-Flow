from .authorization import WorkflowAuthorizationService
from .history_permissions import HISTORY_ACTION
from .models import FormDefinition, FormField, FormRepeatableGroup, WorkflowStepExecution
from .permission_context import PermissionContext


class HistoryBrowserService:
    """
    Read immutable History snapshots for presentation.

    HistoryService owns snapshot creation. This service owns querying,
    authorization, and optional device filtering of already-stored snapshots.
    """

    @staticmethod
    def _base_queryset(*, instance_id=None, device_id=None):
        queryset = (
            WorkflowStepExecution.objects
            .filter(
                is_submitted=True,
                data__has_key="history",
            )
            .select_related(
                "instance",
                "instance__workflow",
                "instance__current_step",
                "workflow_step",
                "performed_by",
            )
            .order_by("-submitted_at", "-pk")
        )

        if instance_id is not None:
            queryset = queryset.filter(instance_id=instance_id)

        if device_id is not None:
            queryset = queryset.filter(
                instance__instance_devices__device_id=device_id,
            ).distinct()

        return queryset

    @staticmethod
    def _is_authorized(*, execution, user):
        return WorkflowAuthorizationService.has_permission(
            user=user,
            workflow=execution.instance.workflow,
            action=HISTORY_ACTION,
            step=execution.workflow_step,
            instance=execution.instance,
        )

    @staticmethod
    def _filter_snapshot_by_permissions(
        *,
        snapshot,
        execution,
        user,
        form=None,
        permission_context=None,
    ):
        if not isinstance(snapshot, dict):
            return None

        if form is None:
            form = (
                FormDefinition.objects
                .filter(workflow=execution.instance.workflow, is_active=True)
                .prefetch_related(
                    "sections__fields",
                    "sections__repeatable_groups__fields",
                )
                .first()
            )
        if form is None:
            return snapshot

        if permission_context is None:
            permission_context = PermissionContext.build(
                workflow=execution.instance.workflow,
                form=form,
                step=execution.workflow_step,
                user=user,
            )

        fields_by_code = {}
        groups_by_code = {}
        for section in form.sections.filter(is_active=True):
            for field in section.fields.filter(is_active=True):
                fields_by_code[field.code] = field
            for group in section.repeatable_groups.filter(is_active=True):
                groups_by_code[group.code] = group

        def field_allowed(field):
            permission = permission_context.field(field)
            return permission.can_view or permission.can_edit

        def filter_fields(field_items):
            result = []
            for item in field_items or []:
                if not isinstance(item, dict):
                    continue
                field = fields_by_code.get(item.get("code"))
                if field is not None and field_allowed(field):
                    result.append(item)
            return result

        def filter_group(group_snapshot):
            if not isinstance(group_snapshot, dict):
                return None
            group = groups_by_code.get(group_snapshot.get("code"))
            if group is None:
                return None
            group_permission = permission_context.group(group)
            if not (group_permission.can_view or group_permission.can_edit):
                return None

            filtered = {**group_snapshot, "items": []}
            for item in group_snapshot.get("items", []):
                if not isinstance(item, dict):
                    continue
                filtered_item = {**item}
                filtered_item["fields"] = filter_fields(item.get("fields", []))
                child_groups = [
                    child
                    for child in (
                        filter_group(child)
                        for child in item.get("child_groups", [])
                    )
                    if child is not None
                ]
                if child_groups:
                    filtered_item["child_groups"] = child_groups
                else:
                    filtered_item.pop("child_groups", None)
                filtered["items"].append(filtered_item)

            return filtered if filtered["items"] else None

        filtered_snapshot = {
            **snapshot,
            "fields": filter_fields(snapshot.get("fields", [])),
            "repeatable_groups": [
                filtered_group
                for filtered_group in (
                    filter_group(group)
                    for group in snapshot.get("repeatable_groups", [])
                )
                if filtered_group is not None
            ],
        }
        return filtered_snapshot

    @staticmethod
    def _device_snapshot(*, snapshot, device_id):
        if not isinstance(snapshot, dict):
            return None

        matched_groups = []
        for group in snapshot.get("repeatable_groups", []):
            if not isinstance(group, dict):
                continue

            matched_items = [
                item
                for item in group.get("items", [])
                if isinstance(item, dict)
                and item.get("device_id") == device_id
            ]

            if matched_items:
                matched_groups.append(
                    {
                        **group,
                        "items": matched_items,
                    }
                )

        # Device History deliberately keeps the complete top-level field
        # history. The device is only the filter that selects relevant
        # repeatable device rows.
        if not matched_groups and not snapshot.get("fields"):
            return None

        return {
            **snapshot,
            "repeatable_groups": matched_groups,
        }

    @classmethod
    def get_history(cls, *, user, instance_id=None, device_id=None):
        history = []
        form_cache = {}
        permission_cache = {}
        authorization_cache = {}

        for execution in cls._base_queryset(
            instance_id=instance_id,
            device_id=device_id,
        ):
            authorization_key = (
                execution.instance.workflow_id,
                execution.workflow_step_id,
                getattr(user, "pk", None),
            )
            if authorization_key not in authorization_cache:
                authorization_cache[authorization_key] = cls._is_authorized(
                    execution=execution,
                    user=user,
                )
            if not authorization_cache[authorization_key]:
                continue

            snapshot = execution.data.get("history") if execution.data else None

            if device_id is not None:
                snapshot = cls._device_snapshot(
                    snapshot=snapshot,
                    device_id=device_id,
                )

            if not isinstance(snapshot, dict):
                continue

            workflow_id = execution.instance.workflow_id
            form = form_cache.get(workflow_id)
            if workflow_id not in form_cache:
                form = (
                    FormDefinition.objects
                    .filter(
                        workflow_id=workflow_id,
                        is_active=True,
                    )
                    .prefetch_related(
                        "sections__fields",
                        "sections__repeatable_groups__fields",
                    )
                    .first()
                )
                form_cache[workflow_id] = form

            permission_key = (
                workflow_id,
                execution.workflow_step_id,
                getattr(user, "pk", None),
            )
            permission_context = permission_cache.get(permission_key)
            if permission_key not in permission_cache:
                permission_context = (
                    PermissionContext.build(
                        workflow=execution.instance.workflow,
                        form=form,
                        step=execution.workflow_step,
                        user=user,
                    )
                    if form is not None
                    else None
                )
                permission_cache[permission_key] = permission_context

            snapshot = cls._filter_snapshot_by_permissions(
                snapshot=snapshot,
                execution=execution,
                user=user,
                form=form,
                permission_context=permission_context,
            )
            if snapshot is None:
                continue

            history.append(
                {
                    "execution": execution,
                    "snapshot": snapshot,
                }
            )

        return history

    @classmethod
    def has_any_history(cls, *, user, instance_id=None, device_id=None):
        """
        Return True when at least one matching history snapshot exists and
        the user is authorized to read at least one of those snapshots.
        """
        return bool(
            cls.get_history(
                user=user,
                instance_id=instance_id,
                device_id=device_id,
            )
        )

    @classmethod
    def has_stored_history(cls, *, instance_id=None, device_id=None):
        return cls._base_queryset(
            instance_id=instance_id,
            device_id=device_id,
        ).exists()
