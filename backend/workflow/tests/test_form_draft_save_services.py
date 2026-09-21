from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_save_services import (
    FormDraftSaveResult,
    FormDraftSaveService,
)
from workflow.models import (
    FormDefinition,
    FormSection,
    Workflow,
    WorkflowInstance,
    WorkflowStep,
    WorkflowStepExecution,
)


class FormDraftSaveServiceContractTests(TestCase):

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="draft-save-user",
            password="password",
        )
        self.workflow = Workflow.objects.create(
            name="Draft Save Workflow",
            code="DRAFT_SAVE_WF",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Draft Step",
            code="DRAFT_STEP",
            order=1,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Draft Form",
        )
        FormSection.objects.create(
            form=self.form,
            name="Draft Section",
            code="DRAFT_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
        )
        self.execution = WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
        )

    def call(self, **overrides):
        params = {
            "instance": self.instance,
            "step": self.step,
            "user": self.user,
            "submitted_data": {},
            "edit_mode": True,
        }
        params.update(overrides)
        return FormDraftSaveService.save(**params)

    def test_valid_context_builds_permission_snapshot(self):
        result = self.call()

        self.assertIsInstance(result, FormDraftSaveResult)
        self.assertFalse(result.saved)
        self.assertTrue(result.is_draft)
        self.assertIsNotNone(result.permission_context)

    def test_save_requires_edit_mode(self):
        with self.assertRaises(ValidationError):
            self.call(edit_mode=False)

    def test_save_rejects_submitted_step(self):
        self.execution.is_submitted = True
        self.execution.save(update_fields=["is_submitted"])

        with self.assertRaises(ValidationError):
            self.call()

    def test_save_rejects_step_from_another_workflow(self):
        other_workflow = Workflow.objects.create(
            name="Other Workflow",
            code="OTHER_DRAFT_WF",
        )
        other_step = WorkflowStep.objects.create(
            workflow=other_workflow,
            name="Other Step",
            code="OTHER_STEP",
            order=1,
        )

        with self.assertRaises(ValidationError):
            self.call(step=other_step)

    def test_save_rejects_non_current_step(self):
        another_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Another Step",
            code="ANOTHER_STEP",
            order=2,
        )

        with self.assertRaises(ValidationError):
            self.call(step=another_step)

    def test_save_requires_step_execution(self):
        self.execution.delete()

        with self.assertRaises(ValidationError):
            self.call()

    def test_missing_form_is_rejected(self):
        self.form.is_active = False
        self.form.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            self.call()
