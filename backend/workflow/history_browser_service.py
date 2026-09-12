from .authorization import WorkflowAuthorizationService
from .history_permissions import HISTORY_ACTION
from .models import WorkflowPermission, WorkflowStepExecution


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

        for execution in cls._base_queryset(
            instance_id=instance_id,
            device_id=device_id,
        ):
            if not cls._is_authorized(
                execution=execution,
                user=user,
            ):
                continue

            snapshot = execution.data.get("history") if execution.data else None

            if device_id is not None:
                snapshot = cls._device_snapshot(
                    snapshot=snapshot,
                    device_id=device_id,
                )

            if not isinstance(snapshot, dict):
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
