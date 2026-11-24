from django.db.models import Exists, OuterRef
from django.utils import timezone

from accounts.models import UserPreference

from .dashboard_services import DashboardService
from workflow.models import WorkflowStepExecution
from workflow.process_summary_services import ProcessSummaryService


NEXT_ACTION_LIMIT = 5
WAITING_OTHERS_LIMIT = 5
UNFINISHED_PROCESSES_LIMIT = 5


class DashboardEnhancementService:
    """Small dashboard-only panels built on the existing workflow rules."""

    def __init__(self, user):
        self.user = user
        self.dashboard = DashboardService(user)

    def get_context(
        self,
        *,
        assigned_instances=None,
        other_actionable_instances=None,
    ):
        waiting_queryset = self.waiting_for_others_queryset()
        unfinished_queryset = self.unfinished_processes_queryset(include_hidden=False)
        unfinished_processes = list(unfinished_queryset[:UNFINISHED_PROCESSES_LIMIT])
        self.dashboard._attach_dashboard_state(unfinished_processes, now=timezone.now())

        next_best_actions = self._next_best_actions(
            assigned_instances=assigned_instances,
            other_actionable_instances=other_actionable_instances,
        )
        summaries = ProcessSummaryService.get_for_instances(
            instances=next_best_actions,
            user=self.user,
        )
        for instance in next_best_actions:
            instance.process_summary = summaries.get(instance.pk, [])

        return {
            "next_best_actions": next_best_actions,
            "waiting_for_others": list(waiting_queryset[:WAITING_OTHERS_LIMIT]),
            "waiting_for_others_count": waiting_queryset.count(),
            "unfinished_processes": unfinished_processes,
            "unfinished_processes_count": unfinished_queryset.count(),
        }

    def _user_preference(self):
        preference, _ = UserPreference.objects.get_or_create(user=self.user)
        return preference

    def hidden_process_ids(self):
        preference = self._user_preference()
        return {
            int(value)
            for value in (preference.hidden_dashboard_process_ids or [])
            if str(value).isdigit()
        }

    def unfinished_processes_queryset(self, *, include_hidden=True):
        queryset = (
            self.dashboard._my_active_queryset()
            .select_related("workflow", "current_step")
            .order_by("-started_at")
        )
        if not include_hidden:
            hidden_ids = self.hidden_process_ids()
            if hidden_ids:
                queryset = queryset.exclude(pk__in=hidden_ids)
        return queryset

    def hide_process(self, instance_id):
        preference = self._user_preference()
        hidden_ids = self.hidden_process_ids()
        hidden_ids.add(int(instance_id))
        preference.hidden_dashboard_process_ids = sorted(hidden_ids)
        preference.save(update_fields=["hidden_dashboard_process_ids"])

    def restore_process(self, instance_id):
        preference = self._user_preference()
        hidden_ids = self.hidden_process_ids()
        hidden_ids.discard(int(instance_id))
        preference.hidden_dashboard_process_ids = sorted(hidden_ids)
        preference.save(update_fields=["hidden_dashboard_process_ids"])

    def waiting_for_others_queryset(self):
        """The user's own active processes currently assigned to another operator."""
        assigned_to_other = Exists(
            WorkflowStepExecution.objects.filter(
                instance_id=OuterRef("pk"),
                workflow_step_id=OuterRef("current_step_id"),
                is_submitted=False,
                assigned_to__isnull=False,
            ).exclude(assigned_to=self.user)
        )
        return (
            self.dashboard._my_active_queryset()
            .filter(current_step__isnull=False)
            .filter(assigned_to_other)
            .select_related("current_step")
            .order_by("-started_at")
        )

    def _next_best_actions(
        self,
        *,
        assigned_instances=None,
        other_actionable_instances=None,
    ):
        """Prioritize supplied dashboard batches, fetching only missing batches."""
        if assigned_instances is None:
            assigned_instances = self.dashboard._pending_instances(
                assigned_only=True,
            )
        if other_actionable_instances is None:
            other_actionable_instances = self.dashboard._pending_instances(
                exclude_assigned=True,
            )

        instances = {
            instance.pk: instance
            for instance in [
                *assigned_instances,
                *other_actionable_instances,
            ]
        }
        instances = list(instances.values())
        self.dashboard._attach_dashboard_state(instances, now=timezone.now())

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
