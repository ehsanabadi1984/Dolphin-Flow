from unittest.mock import patch

from django.test import TestCase

from workflow.form_draft_payloads import NormalizedFormPayload
from workflow.form_draft_submit_services import FormDraftSubmitService
from workflow.models import FormDefinition, FormSection, Workflow, WorkflowInstance


class FormDraftSubmitServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Submit Orchestration Workflow",
            code="SUBMIT_ORCH_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Submit Orchestration Form",
        )
        FormSection.objects.create(
            form=self.form,
            name="Submit Section",
            code="SUBMIT_SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    @patch(
        "workflow.form_draft_submit_services.FormDraftSubmitValidationService"
        ".validate_payload"
    )
    @patch(
        "workflow.form_draft_submit_services.FormDraftValueValidationService"
        ".validate_payload"
    )
    @patch(
        "workflow.form_draft_submit_services.FormDraftCurrentStatePayloadService"
        ".build"
    )
    def test_validate_builds_current_state_then_runs_value_and_completeness(
        self,
        build,
        validate_values,
        validate_completeness,
    ):
        payload = NormalizedFormPayload(
            normal_fields={},
            repeatable_groups={},
        )
        build.return_value = payload

        result = FormDraftSubmitService.validate(
            instance=self.instance,
            form=self.form,
        )

        self.assertIs(result, payload)
        build.assert_called_once_with(
            instance=self.instance,
            form=self.form,
        )
        validate_values.assert_called_once_with(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )
        validate_completeness.assert_called_once_with(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )
        self.assertLess(
            build.call_args_list[0][0].__len__(),
            1,
        )
