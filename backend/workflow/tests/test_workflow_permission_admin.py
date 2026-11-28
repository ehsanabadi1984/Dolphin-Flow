from django.test import TestCase

from workflow.admin import WorkflowStepPermissionForm, WorkflowStepPermissionInline
from workflow.models import WorkflowPermission


class WorkflowStepPermissionAdminTests(TestCase):
    def test_step_action_exposes_accept_and_reject_choices(self):
        form = WorkflowStepPermissionForm()

        self.assertIn(("ACCEPT", "تأیید دریافت"), form.fields["action_code"].choices)
        self.assertIn(("REJECT", "رد دریافت"), form.fields["action_code"].choices)
        self.assertEqual(form.fields["action_code"].widget.__class__.__name__, "Select")
        self.assertIn("workflow/js/workflow-step-permission-admin.js", form.Media.js)

    def test_step_action_requires_action_code(self):
        form = WorkflowStepPermissionForm(
            data={
                "action": WorkflowPermission.Action.STEP_ACTION,
                "action_code": "",
                "effect": WorkflowPermission.Effect.ALLOW,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("action_code", form.errors)

    def test_non_step_action_clears_action_code(self):
        form = WorkflowStepPermissionForm(
            data={
                "action": WorkflowPermission.Action.VIEW,
                "action_code": "ACCEPT",
                "effect": WorkflowPermission.Effect.ALLOW,
            }
        )

        self.assertTrue(form.is_valid())
        self.assertIsNone(form.cleaned_data["action_code"])

    def test_step_permission_inline_includes_action_code(self):
        self.assertIn("action_code", WorkflowStepPermissionInline.fields)
        self.assertIs(WorkflowStepPermissionInline.form, WorkflowStepPermissionForm)


class WorkflowStepAssignmentAdminFormTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model

        from workflow.models import Workflow, WorkflowStep

        self.user = get_user_model().objects.create_user(
            username="fixed-assignee",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(name="Assignment admin workflow")
        self.source_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Source",
            order=1,
        )
        self.target_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Target",
            order=2,
        )
        self.other_workflow = Workflow.objects.create(name="Other admin workflow")
        self.other_step = WorkflowStep.objects.create(
            workflow=self.other_workflow,
            name="Other source",
            order=1,
        )

    def form_data(self, *, policy, assigned_to="", source_step=""):
        return {
            "workflow": str(self.workflow.pk),
            "name": "Configured target",
            "order": "3",
            "assignment_policy": policy,
            "assigned_to": str(assigned_to) if assigned_to else "",
            "assignment_source_step": (
                str(source_step) if source_step else ""
            ),
            "description": "",
        }

    def test_fixed_policy_requires_assignee(self):
        from workflow.admin import WorkflowStepAdminForm
        from workflow.models import WorkflowStep

        form = WorkflowStepAdminForm(
            data=self.form_data(
                policy=WorkflowStep.AssignmentPolicy.FIXED,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("assigned_to", form.errors)

    def test_fixed_policy_accepts_selected_assignee(self):
        from workflow.admin import WorkflowStepAdminForm
        from workflow.models import WorkflowStep

        form = WorkflowStepAdminForm(
            data=self.form_data(
                policy=WorkflowStep.AssignmentPolicy.FIXED,
                assigned_to=self.user.pk,
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["assigned_to"], self.user)

    def test_step_completer_requires_source_step(self):
        from workflow.admin import WorkflowStepAdminForm
        from workflow.models import WorkflowStep

        form = WorkflowStepAdminForm(
            data=self.form_data(
                policy=WorkflowStep.AssignmentPolicy.STEP_COMPLETER,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("assignment_source_step", form.errors)

    def test_step_completer_accepts_source_from_same_workflow(self):
        from workflow.admin import WorkflowStepAdminForm
        from workflow.models import WorkflowStep

        form = WorkflowStepAdminForm(
            data=self.form_data(
                policy=WorkflowStep.AssignmentPolicy.STEP_COMPLETER,
                source_step=self.source_step.pk,
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["assignment_source_step"],
            self.source_step,
        )

    def test_source_step_queryset_is_limited_to_selected_workflow(self):
        from workflow.admin import WorkflowStepAdminForm
        from workflow.models import WorkflowStep

        form = WorkflowStepAdminForm(
            data=self.form_data(
                policy=WorkflowStep.AssignmentPolicy.STEP_COMPLETER,
                source_step=self.other_step.pk,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("assignment_source_step", form.errors)
        self.assertQuerySetEqual(
            form.fields["assignment_source_step"].queryset.order_by("pk"),
            [self.source_step, self.target_step],
        )

    def test_other_policies_reject_assignment_source_step(self):
        from workflow.admin import WorkflowStepAdminForm
        from workflow.models import WorkflowStep

        form = WorkflowStepAdminForm(
            data=self.form_data(
                policy=WorkflowStep.AssignmentPolicy.INSTANCE_STARTER,
                source_step=self.source_step.pk,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("assignment_source_step", form.errors)

    def test_admin_form_loads_conditional_assignment_fields_script(self):
        from workflow.admin import WorkflowStepAdminForm

        self.assertIn(
            "workflow/js/workflow-step-assignment-admin.js",
            WorkflowStepAdminForm.Media.js,
        )
