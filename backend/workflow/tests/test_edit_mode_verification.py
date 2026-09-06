"""
Simple verification test for edit_mode enforcement.
This test verifies that the edit_mode check is working correctly.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase

from workflow.models import (
    FormDefinition,
    FormField,
    FormSection,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
    FormData,
)

from workflow.form_services import DynamicFormService


User = get_user_model()


class EditModeVerificationTest(TestCase):
    """Simple verification that edit_mode is enforced."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="verification_test_user",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="Verification Test Workflow",
            code="VERIFICATION_TEST_WF",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Test Step",
            code="TEST_STEP",
            order=1,
            is_active=True,
        )

        cls.membership = WorkflowMembership.objects.create(
            workflow=cls.workflow,
            user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        cls.form = FormDefinition.objects.create(
            workflow=cls.workflow,
            name="Test Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Test Section",
            code="TEST_SECTION",
            order=1,
            is_active=True,
        )

        # Only a simple text field - no repeatable groups
        cls.field = FormField.objects.create(
            section=cls.section,
            name="simple_field",
            code="simple_field",
            field_type=FormField.FieldType.TEXT,
            label="Simple Field",
            order=1,
            is_active=True,
            repeatable_group=None,
        )

        from workflow.models import FieldAccess
        FieldAccess.objects.create(
            field=cls.field,
            step=cls.step,
            user=cls.user,
            can_view=True,
            can_edit=True,
        )

    def _create_instance(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
            status=WorkflowInstance.Status.ACTIVE,
        )

        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step,
            performed_by=self.user,
        )

        return instance

    def test_edit_mode_false_rejects_save(self):
        """Test that edit_mode=False rejects save."""
        instance = self._create_instance()

        with self.assertRaises(ValidationError) as ctx:
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={"simple_field": "test value"},
                edit_mode=False,
            )

        # Verify the error is about edit_mode
        self.assertIn("ویرایش", str(ctx.exception))
        print(f"✓ edit_mode=False correctly rejected: {ctx.exception}")

    def test_edit_mode_true_accepts_save(self):
        """Test that edit_mode=True accepts save."""
        instance = self._create_instance()

        form_data = DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={"simple_field": "test value"},
            edit_mode=True,
        )

        self.assertIsNotNone(form_data)
        self.assertEqual(form_data.data.get("simple_field"), "test value")
        print(f"✓ edit_mode=True correctly accepted save")

    def test_clear_form_edit_mode_false_rejects(self):
        """Test that clear_form with edit_mode=False is rejected."""
        instance = self._create_instance()

        # First save some data
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={"simple_field": "test value"},
            edit_mode=True,
        )

        # Try to clear with edit_mode=False
        with self.assertRaises(PermissionDenied) as ctx:
            DynamicFormService.clear_form_for_step(
                instance=instance,
                user=self.user,
                edit_mode=False,
            )

        # Verify the error is about edit_mode
        self.assertIn("ویرایش", str(ctx.exception))
        print(f"✓ clear_form with edit_mode=False correctly rejected: {ctx.exception}")

    def test_clear_form_edit_mode_true_accepts(self):
        """Test that clear_form with edit_mode=True is accepted."""
        instance = self._create_instance()

        # First save some data
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={"simple_field": "test value"},
            edit_mode=True,
        )

        # Clear with edit_mode=True
        DynamicFormService.clear_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        # Verify data is cleared
        form_data = FormData.objects.filter(instance=instance).first()
        self.assertNotIn("simple_field", form_data.data)
        print(f"✓ clear_form with edit_mode=True correctly cleared data")


if __name__ == "__main__":
    import unittest
    unittest.main()
