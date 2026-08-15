from datetime import timedelta

from django.test import TestCase

from workflow.models import (
    BusinessCalendar,
    Workflow,
    WorkflowStep,
    WorkflowStepSLA,
)

class WorkflowStepSLAModelTests(TestCase):

    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="SLA Test Workflow",
            code="SLA_TEST_WORKFLOW",
        )

        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="SLA Test Step",
            code="SLA_TEST_STEP",
            order=1,
        )

        self.calendar = BusinessCalendar.objects.create(
            name="SLA Test Calendar",
        )

    def test_create_sla(self):
        sla = WorkflowStepSLA.objects.create(
            step=self.step,
            calendar=self.calendar,
            duration=timedelta(hours=4),
            warning_before=timedelta(hours=1),
        )

        self.assertEqual(sla.step, self.step)
        self.assertEqual(sla.calendar, self.calendar)
        self.assertEqual(sla.duration, timedelta(hours=4))
        self.assertEqual(
            sla.warning_before,
            timedelta(hours=1),
        )
        self.assertTrue(sla.is_active)

    def test_step_can_have_only_one_sla(self):
        WorkflowStepSLA.objects.create(
            step=self.step,
            calendar=self.calendar,
            duration=timedelta(hours=4),
        )

        with self.assertRaises(Exception):
            WorkflowStepSLA.objects.create(
                step=self.step,
                calendar=self.calendar,
                duration=timedelta(hours=8),
            )

    def test_warning_before_can_be_empty(self):
        sla = WorkflowStepSLA.objects.create(
            step=self.step,
            calendar=self.calendar,
            duration=timedelta(hours=4),
        )

        self.assertIsNone(sla.warning_before)

    def test_sla_can_be_disabled(self):
        sla = WorkflowStepSLA.objects.create(
            step=self.step,
            calendar=self.calendar,
            duration=timedelta(hours=4),
            is_active=False,
        )

        self.assertFalse(sla.is_active)