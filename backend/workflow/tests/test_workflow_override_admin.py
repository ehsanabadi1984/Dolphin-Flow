from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import TestCase

from workflow.admin import dolphin_admin_site
from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
)
from workflow.override_admin import WorkflowInstanceOverrideForm


User = get_user_model()


class WorkflowOverrideAdminTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="override_ui_admin",
            password="test-password",
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        self.operator = User.objects.create_user(
            username="override_ui_operator",
            password="test-password",
            is_active=True,
        )
        self.workflow = Workflow.objects.create(
            name="Override Admin Workflow",
            code="OVERRIDE_ADMIN_TEST",
            is_active=True,
        )
        self.current_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Current",
            order=1,
            is_active=True,
        )
        self.target_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Target",
            order=2,
            is_active=True,
            assignment_policy=WorkflowStep.AssignmentPolicy.PREVIOUS_COMPLETER_SELECTS,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.operator,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.target_step,
            user=self.operator,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.current_step,
            started_by=self.operator,
            status=WorkflowInstance.Status.ACTIVE,
        )
        self.client.force_login(self.admin)
        self.url = reverse(
            "dolphin_admin:workflow_workflowinstance_override",
            args=[self.instance.pk],
        )

    def test_get_form_lists_only_eligible_candidates(self):
        inactive = User.objects.create_user(
            username="override_ui_inactive",
            password="test-password",
            is_active=False,
        )
        form = WorkflowInstanceOverrideForm(instance=self.instance)

        self.assertQuerySetEqual(
            form.fields["selected_assignee"].queryset,
            [self.operator],
        )
        self.assertNotIn(
            inactive,
            form.fields["selected_assignee"].queryset,
        )

    def test_post_passes_selected_assignee_to_override_service(self):
        response = self.client.post(
            self.url,
            {
                "target_step": self.target_step.pk,
                "selected_assignee": self.operator.pk,
                "reason": "اصلاح مسئول مرحله",
            },
        )

        self.assertEqual(response.status_code, 302)
        execution = WorkflowStepExecution.objects.get(
            instance=self.instance,
            workflow_step=self.target_step,
            entered_by=self.admin,
        )
        self.assertEqual(execution.assigned_to, self.operator)
        history = WorkflowStepAssignmentHistory.objects.get(
            step_execution=execution,
        )
        self.assertEqual(history.new_assignee, self.operator)
        self.assertEqual(history.changed_by, self.admin)
        self.assertEqual(
            history.source,
            WorkflowStepAssignmentHistory.Source.OVERRIDE,
        )

    def test_post_requires_assignee_for_previous_completer_policy(self):
        response = self.client.post(
            self.url,
            {
                "target_step": self.target_step.pk,
                "reason": "اصلاح بدون مسئول",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "selected_assignee",
            response.context["form"].errors,
        )
        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=self.instance,
                workflow_step=self.target_step,
                entered_by=self.admin,
            ).exists()
        )
