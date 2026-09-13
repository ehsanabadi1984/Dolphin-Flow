from django.db.models import Q

from workflow.models import Notification, WorkflowInstance

from .dashboard_services import DashboardService, _can_view_q


NEXT_ACTION_LIMIT = 5
WAITING_OTHERS_LIMIT = 5
PERSONAL_UPDATES_LIMIT = 5


class DashboardEnhancementService:
    """Small dashboard-only panels built on the existing workflow rules."""

    def __init__(self, user):
        self.user = user
        self.dashboard = DashboardService(user)

    def get_context(self):
        return {
            "next_best_actions": self._next_best_actions(),
            "waiting_for_others": self._waiting_for_others(),
            "personal_updates": self._personal_updates(),
        }

    def _next_best_actions(self):
        """Return the most urgent actionable items without changing task rules."""
        assigned = self.dashboard._pending_instances(assigned_only=True)
        other_actionable = self.dashboard._pending_instances(exclude_assigned=True)

        instances = {instance.pk: instance for instance in [*assigned, *other_actionable]}
        instances = list(instances.values())
        self.dashboard._attach_dashboard_state(instances, now=__import__("django.utils.timezone", fromlist=["timezone"]).timezone.now())

        priority = {
            "breached": 0,
            "warning": 1,
            "on_track": 2,
            "none": 3,
        }

        instances.sort(
            key=lambda instance: (
                priority.get(instance.dashboard_sla["status"], 4),
                instance.dashboard_sla["due_at"] is None,
                instance.dashboard_sla["due_at"] or instance.started_at,
                instance.started_at,
            )
        )

        for instance in instances[:NEXT_ACTION_LIMIT]:
            status = instance.dashboard_sla["status"]
            if status == "breached":
                instance.dashboard_priority_label = "فوری"
                instance.dashboard_priority_class = "danger"
            elif status == "warning":
                instance.dashboard_priority_label = "اولویت بالا"
                instance.dashboard_priority_class = "warning"
            else:
                instance.dashboard_priority_label = "قابل اقدام"
                instance.dashboard_priority_class = "normal"

        return instances[:NEXT_ACTION_LIMIT]

    def _waiting_for_others(self):
        """The user's own active processes currently assigned to another operator."""
        return list(
            self.dashboard._my_active_queryset()
            .filter(
                current_step__isnull=False,
                current_step__assigned_to__isnull=False,
            )
            .exclude(current_step__assigned_to_id=self.user.pk)
            .select_related("current_step", "current_step__assigned_to")[:WAITING_OTHERS_LIMIT]
        )

    def _personal_updates(self):
        """Unread notifications addressed to this operator only."""
        return list(
            Notification.objects
            .filter(
                recipient=self.user,
                is_read=False,
            )
            .select_related("workflow_instance", "workflow_step")
            .order_by("-created_at")[:PERSONAL_UPDATES_LIMIT]
        )
