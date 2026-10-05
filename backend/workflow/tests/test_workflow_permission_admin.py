from django.test import TestCase

from workflow.admin import WorkflowStepPermissionForm, WorkflowStepPermissionInline
from workflow.models import WorkflowPermission


class WorkflowStepPermissionAdminTests(TestCase):
    def test_step_action_exposes_accept_and_reject_choices(self):
        form = WorkflowStepPermissionForm()

        self.assertIn(("ACCEPT", "تأیید دریافت"), form.fields["action_code"].choices)
        self.assertIn(("REJECT", "رد دریافت"), form.fields["action_code"].choices)

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
