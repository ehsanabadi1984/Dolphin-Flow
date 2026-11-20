from django.test import TestCase
from django.contrib.auth import get_user_model

from workflow.admin import WorkflowTransitionAdminForm, WorkflowTransitionInline
from workflow.models import Workflow, WorkflowStep, WorkflowTransition


class WorkflowTransitionAcceptanceConfigurationTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Acceptance Configuration Test",
        )
        self.step_a = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step A",
            order=1,
        )
        self.step_b = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step B",
            order=2,
        )
        self.step_c = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step C",
            order=3,
        )

    def test_acceptance_is_disabled_by_default(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
        )

        self.assertFalse(transition.requires_acceptance)

    def test_acceptance_can_be_enabled_per_transition(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_a,
            to_step=self.step_b,
            name="A to B",
            requires_acceptance=True,
        )

        self.assertTrue(transition.requires_acceptance)

    def test_acceptance_transition_can_define_reject_target(self):
        transition = WorkflowTransition.objects.create(
            workflow=self.workflow,
            from_step=self.step_b,
            to_step=self.step_c,
            name="B to C",
            requires_acceptance=True,
            reject_to_step=self.step_a,
        )

        self.assertEqual(transition.reject_to_step, self.step_a)

    def test_admin_form_reject_target_requires_acceptance(self):
        form = WorkflowTransitionAdminForm(
            data={
                "workflow": self.workflow.pk,
                "from_step": self.step_b.pk,
                "to_step": self.step_c.pk,
                "name": "B to C",
                "is_active": True,
                "requires_acceptance": False,
                "reject_to_step": self.step_a.pk,
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("مرحله بازگشت پس از رد", form.non_field_errors()[0])

    def test_admin_form_accepts_dynamic_reject_target(self):
        form = WorkflowTransitionAdminForm(
            data={
                "workflow": self.workflow.pk,
                "from_step": self.step_b.pk,
                "to_step": self.step_c.pk,
                "name": "B to C",
                "is_active": True,
                "requires_acceptance": True,
                "reject_to_step": self.step_a.pk,
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["reject_to_step"],
            self.step_a,
        )

    def _notification_form_data(self, **overrides):
        data = {
            "workflow": self.workflow.pk,
            "from_step": self.step_a.pk,
            "to_step": self.step_b.pk,
            "name": "Notification policy transition",
            "is_active": True,
            "requires_acceptance": True,
            "accept_notification_policy": "SOURCE_COMPLETER",
            "accept_notification_user": "",
            "reject_notification_policy": "SOURCE_COMPLETER",
            "reject_notification_user": "",
        }
        data.update(overrides)
        return data

    def test_fixed_user_is_required_independently_for_accept_and_reject(self):
        for policy_field, user_field in (
            ("accept_notification_policy", "accept_notification_user"),
            ("reject_notification_policy", "reject_notification_user"),
        ):
            with self.subTest(outcome=policy_field):
                data = self._notification_form_data(**{
                    policy_field: "FIXED_USER",
                    user_field: "",
                })
                form = WorkflowTransitionAdminForm(data=data)
                self.assertFalse(form.is_valid())
                self.assertIn(user_field, form.errors)

    def test_fixed_notification_recipient_may_be_outside_workflow(self):
        user = get_user_model().objects.create_user(
            username="external-recipient",
            password="test-password",
        )
        form = WorkflowTransitionAdminForm(
            data=self._notification_form_data(
                accept_notification_policy="FIXED_USER",
                accept_notification_user=user.pk,
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["accept_notification_user"], user)

    def test_non_fixed_policy_clears_submitted_fixed_user(self):
        user = get_user_model().objects.create_user(
            username="stale-recipient",
            password="test-password",
        )
        form = WorkflowTransitionAdminForm(
            data=self._notification_form_data(
                accept_notification_policy="WORKFLOW_STARTER",
                accept_notification_user=user.pk,
            )
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["accept_notification_user"])

    def test_inactive_user_cannot_be_selected_as_fixed_recipient(self):
        user = get_user_model().objects.create_user(
            username="inactive-recipient",
            password="test-password",
            is_active=False,
        )
        form = WorkflowTransitionAdminForm(
            data=self._notification_form_data(
                reject_notification_policy="FIXED_USER",
                reject_notification_user=user.pk,
            )
        )

        self.assertFalse(form.is_valid())
        self.assertIn("reject_notification_user", form.errors)

    def test_workflow_inline_exposes_both_notification_policies_and_users(self):
        self.assertIn("accept_notification_policy", WorkflowTransitionInline.fields)
        self.assertIn("accept_notification_user", WorkflowTransitionInline.fields)
        self.assertIn("reject_notification_policy", WorkflowTransitionInline.fields)
        self.assertIn("reject_notification_user", WorkflowTransitionInline.fields)
