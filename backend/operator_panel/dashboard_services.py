from django.utils import timezone

from workflow.authorization import WorkflowAuthorizationService
from workflow.models import (
    WorkflowInstance,
    WorkflowPermission,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
)


class DashboardService:
    """Build the operator dashboard from the existing workflow domain."""

    def __init__(self, user):
        self.user = user

    def get_context(self):
        now = timezone.now()
        today = now.date()

        my_instances = (
            WorkflowInstance.objects
            .filter(started_by=self.user)
            .exclude(status=WorkflowInstance.Status.DRAFT)
            .select_related("workflow", "current_step")
        )

        active_instances = list(
            my_instances
            .filter(status=WorkflowInstance.Status.ACTIVE)
            .order_by("-started_at")[:10]
        )

        for instance in active_instances:
            instance.dashboard_tracker = self.build_tracker(instance)
            instance.dashboard_can_execute = self.can_take_action(instance)

        my_tasks = self._get_pending_instances(assigned_only=True)
        pending_instances = self._get_pending_instances(exclude_assigned=True)

        return {
            "summary": {
                "today": my_instances.filter(started_at__date=today).count(),
                "pending": len(pending_instances),
                "tasks": len(my_tasks),
                "active": my_instances.filter(
                    status=WorkflowInstance.Status.ACTIVE,
                ).count(),
                "completed": my_instances.filter(
                    status=WorkflowInstance.Status.COMPLETED,
                ).count(),
            },
            "active_processes": active_instances,
            "pending_actions": pending_instances,
            "my_tasks": my_tasks,
            "recent_activity": self._get_recent_activity(),
            "startable_workflows": (
                WorkflowAuthorizationService
                .get_startable_workflows(self.user)
                .order_by("name")
            ),
        }

    def get_sidebar_counts(self):
        active_instances = self._get_accessible_active_instances()
        tasks = 0
        pending = 0

        for instance in active_instances:
            if not instance.current_step:
                continue

            if instance.current_step.assigned_to_id == self.user.pk:
                tasks += 1
            elif self.can_take_action(instance):
                pending += 1

        return {
            "tasks": tasks,
            "pending": pending,
            "active": len(active_instances),
        }

    def can_take_action(self, instance):
        if instance.status != WorkflowInstance.Status.ACTIVE:
            return False
        if not instance.current_step:
            return False

        if WorkflowAuthorizationService.has_permission(
            user=self.user,
            workflow=instance.workflow,
            action=WorkflowPermission.Action.EXECUTE,
            step=instance.current_step,
            instance=instance,
        ):
            return True

        return bool(
            WorkflowAuthorizationService.get_allowed_transitions(
                user=self.user,
                workflow=instance.workflow,
                from_step=instance.current_step,
            )
        )

    def _get_accessible_active_instances(self, limit=None):
        queryset = (
            WorkflowInstance.objects
            .filter(
                status=WorkflowInstance.Status.ACTIVE,
                workflow__memberships__user=self.user,
                workflow__memberships__is_active=True,
            )
            .select_related("workflow", "current_step")
            .distinct()
            .order_by("-started_at")
        )

        if limit:
            queryset = queryset[:limit]

        return list(queryset)

    def _get_pending_instances(
        self,
        assigned_only=False,
        exclude_assigned=False,
    ):
        queryset = self._get_accessible_active_instances(limit=50)

        pending = []
        for instance in queryset:
            if not instance.current_step:
                continue

            is_assigned = (
                instance.current_step.assigned_to_id == self.user.pk
            )

            if assigned_only and not is_assigned:
                continue

            if exclude_assigned and is_assigned:
                continue

            if self.can_take_action(instance):
                instance.dashboard_tracker = self.build_tracker(instance)
                pending.append(instance)

        return pending

    def _get_recent_activity(self, limit=10):
        transitions = list(
            WorkflowTransitionExecution.objects
            .filter(
                instance__workflow__memberships__user=self.user,
                instance__workflow__memberships__is_active=True,
            )
            .select_related(
                "instance",
                "instance__workflow",
                "transition",
                "transition__from_step",
                "transition__to_step",
                "performed_by",
            )
            .distinct()
            .order_by("-performed_at")[:limit]
        )

        activities = []
        for item in transitions:
            if item.transition.to_step:
                title = (
                    f"فرآیند «{item.instance.workflow.name}» "
                    f"به «{item.transition.to_step.name}» منتقل شد"
                )
            else:
                title = f"فرآیند «{item.instance.workflow.name}» تکمیل شد"

            activities.append({
                "title": title,
                "meta": f"فرآیند #{item.instance.pk}",
                "performed_at": item.performed_at,
            })

        return sorted(
            activities,
            key=lambda item: item["performed_at"],
            reverse=True,
        )[:limit]

    def build_tracker(self, instance):
        steps = list(
            instance.workflow.steps
            .filter(is_active=True)
            .order_by("order")
        )

        submitted_step_ids = set(
            WorkflowStepExecution.objects
            .filter(
                instance=instance,
                is_submitted=True,
            )
            .values_list("workflow_step_id", flat=True)
        )

        transitioned_from_ids = set(
            WorkflowTransitionExecution.objects
            .filter(instance=instance)
            .values_list("transition__from_step_id", flat=True)
        )

        completed_ids = submitted_step_ids | transitioned_from_ids

        tracker = []
        for step in steps:
            if instance.status == WorkflowInstance.Status.COMPLETED:
                state = "completed"
            elif instance.status in {
                WorkflowInstance.Status.CANCELLED,
                WorkflowInstance.Status.SUSPENDED,
            }:
                state = "current" if step.pk == instance.current_step_id else "future"
            elif step.pk == instance.current_step_id:
                state = "current"
            elif step.pk in completed_ids:
                state = "completed"
            else:
                state = "future"

            tracker.append({
                "step": step,
                "state": state,
            })

        return tracker
