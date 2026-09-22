from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormSection,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)


User = get_user_model()


class WorkflowInstancePostAdapterIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="operator-post-user",
            password="password",
        )
        self.workflow = Workflow.objects.create(
            name="Operator POST Workflow",
            code="OPERATOR_POST_WF",
            is_active=True,
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Operator POST Step",
            code="OPERATOR_POST_STEP",
            order=1,
            is_active=True,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Operator POST Form",
            is_active=True,
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Operator POST Section",
            code="OPERATOR_POST_SECTION",
            order=1,
        )
        self.name_field = FormField.objects.create(
            section=self.section,
            name="Customer Name",
            code="customer_name",
            label="Customer Name",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        self.enabled_field = FormField.objects.create(
            section=self.section,
            name="Enabled",
            code="enabled",
            label="Enabled",
            field_type=FormField.FieldType.BOOLEAN,
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
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        for field in (self.name_field, self.enabled_field):
            FieldAccess.objects.create(
                field=field,
                step=self.step,
                user=self.user,
                can_view=True,
                can_edit=True,
            )
        self.client.force_login(self.user)

    def test_workflow_instance_post_uses_draft_pipeline_and_persists_normal_fields(self):
        response = self.client.post(
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
            {
                "customer_name": "Ehsan",
                "enabled": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse(
                "operator_panel:workflow_instance",
                args=[self.instance.pk],
            ),
        )

        form_data = FormData.objects.get(instance=self.instance)
        self.assertEqual(
            form_data.data,
            {
                "customer_name": "Ehsan",
                "enabled": True,
            },
        )
