import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowStep,
    WorkflowStepExecution,
)
from workflow.override_services import WorkflowOverrideService


User = get_user_model()


class WorkflowOverrideServiceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="override_admin",
            password="test-password",
            is_active=True,
            is_staff=True,
        )
        self.operator = User.objects.create_user(
            username="override_operator",
            password="test-password",
            is_active=True,
            is_staff=False,
        )

        self.workflow = Workflow.objects.create(
            name="Override Test Workflow",
            code="OVERRIDE_TEST",
            is_active=True,
        )
        self.other_workflow = Workflow.objects.create(
            name="Other Workflow",
            code="OVERRIDE_OTHER",
            is_active=True,
        )

        self.step_a = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="A",
            order=1,
            is_active=True,
        )
        self.step_b = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="B",
            order=2,
            is_active=True,
        )
        self.step_c = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="C",
            order=3,
            is_active=True,
        )
        self.inactive_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Inactive",
            order=4,
            is_active=False,
        )
        self.other_step = WorkflowStep.objects.create(
            workflow=self.other_workflow,
            name="Other",
            order=1,
            is_active=True,
        )

        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step_c,
            started_by=self.operator,
            status=WorkflowInstance.Status.ACTIVE,
        )
        WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_a,
            performed_by=self.operator,
            is_submitted=True,
        )
        WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_b,
            performed_by=self.operator,
            is_submitted=True,
        )
        self.current_execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step_c,
            performed_by=self.operator,
            is_submitted=False,
        )

    def test_override_creates_new_unsubmitted_execution(self):
        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="اصلاح اشتباه مسیر",
        )

        self.instance.refresh_from_db()
        self.current_execution.refresh_from_db()

        self.assertEqual(self.instance.current_step_id, self.step_b.id)
        self.assertEqual(self.instance.status, WorkflowInstance.Status.ACTIVE)
        self.assertFalse(new_execution.is_submitted)
        self.assertEqual(new_execution.workflow_step_id, self.step_b.id)
        self.assertEqual(new_execution.data["override"]["from_step_id"], self.step_c.id)
        self.assertEqual(new_execution.data["override"]["reason"], "اصلاح اشتباه مسیر")
        self.assertTrue(self.current_execution.pk != new_execution.pk)
        self.assertFalse(self.current_execution.is_submitted)

    def test_completed_instance_is_reopened(self):
        self.instance.current_step = None
        self.instance.status = WorkflowInstance.Status.COMPLETED
        self.instance.completed_at = timezone.now()
        self.instance.save(update_fields=["current_step", "status", "completed_at"])

        new_execution = WorkflowOverrideService.override_instance_step(
            instance=self.instance,
            target_step=self.step_b,
            performed_by=self.admin,
            reason="بازگشت برای اصلاح",
        )

        self.instance.refresh_from_db()

        self.assertEqual(self.instance.status, WorkflowInstance.Status.ACTIVE)
        self.assertIsNone(self.instance.completed_at)
        self.assertEqual(self.instance.current_step_id, self.step_b.id)
        self.assertFalse(new_execution.is_submitted)

    def test_rejects_non_admin(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.operator,
                reason="اصلاح مسیر",
            )

    def test_rejects_same_step(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_c,
                performed_by=self.admin,
                reason="اصلاح مسیر",
            )

    def test_rejects_inactive_target(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.inactive_step,
                performed_by=self.admin,
                reason="اصلاح مسیر",
            )

    def test_rejects_other_workflow(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.other_step,
                performed_by=self.admin,
                reason="اصلاح مسیر",
            )

    def test_rejects_cancelled_instance(self):
        self.instance.status = WorkflowInstance.Status.CANCELLED
        self.instance.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.admin,
                reason="اصلاح مسیر",
            )

    def test_rejects_short_reason(self):
        with self.assertRaises(ValidationError):
            WorkflowOverrideService.override_instance_step(
                instance=self.instance,
                target_step=self.step_b,
                performed_by=self.admin,
                reason="بد",
            )
