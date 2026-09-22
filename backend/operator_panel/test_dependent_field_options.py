from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from workflow.models import (
    FieldAccess,
    FormDefinition,
    FormField,
    FormSection,
    LookupItem,
    LookupList,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
)


User = get_user_model()


class DependentFieldOptionsAuthorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="dependent-options-user",
            password="password",
        )
        self.workflow = Workflow.objects.create(
            name="Dependent Options Workflow",
            code="DEPENDENT_OPTIONS_WF",
            is_active=True,
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Dependent Options Step",
            code="DEPENDENT_OPTIONS_STEP",
            order=1,
            is_active=True,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Dependent Options Form",
            is_active=True,
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Dependent Options Section",
            code="DEPENDENT_OPTIONS_SECTION",
            order=1,
            is_active=True,
        )
        self.parent_field = FormField.objects.create(
            section=self.section,
            name="Parent",
            code="parent",
            label="Parent",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            order=0,
            is_active=True,
        )
        self.child_field = FormField.objects.create(
            section=self.section,
            name="Child",
            code="child",
            label="Child",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_parent_field=self.parent_field,
            order=1,
            is_active=True,
        )
        self.lookup_list = LookupList.objects.create(
            name="Dependent Options",
            code="DEPENDENT_OPTIONS_LOOKUP",
        )
        self.parent_item = LookupItem.objects.create(
            lookup_list=self.lookup_list,
            value="parent-1",
            label="Parent 1",
            order=0,
        )
        self.parent_field.choice_lookup_list = self.lookup_list
        self.parent_field.save(update_fields=["choice_lookup_list"])
        LookupItem.objects.create(
            lookup_list=self.lookup_list,
            parent=self.parent_item,
            value="child-1",
            label="Child 1",
            order=0,
        )
        self.child_field.choice_lookup_list = self.lookup_list
        self.child_field.save(update_fields=["choice_lookup_list"])
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        FieldAccess.objects.create(
            field=self.parent_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=self.child_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
        )
        self.client.force_login(self.user)

    def test_dependent_options_require_field_view_permission(self):
        response = self.client.get(
            reverse("operator_panel:dependent_field_options"),
            {
                "instance_id": self.instance.pk,
                "field_id": self.child_field.pk,
                "parent_value": self.parent_item.value,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["options"],
            [{"value": "child-1", "label": "Child 1"}],
        )

        FieldAccess.objects.filter(
            field=self.child_field,
            step=self.step,
            user=self.user,
        ).update(can_view=False)

        response = self.client.get(
            reverse("operator_panel:dependent_field_options"),
            {
                "instance_id": self.instance.pk,
                "field_id": self.child_field.pk,
                "parent_value": self.parent_item.value,
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_dependent_options_cannot_read_field_from_another_workflow(self):
        other_workflow = Workflow.objects.create(
            name="Other Workflow",
            code="OTHER_DEPENDENT_OPTIONS_WF",
            is_active=True,
        )
        other_step = WorkflowStep.objects.create(
            workflow=other_workflow,
            name="Other Step",
            code="OTHER_DEPENDENT_OPTIONS_STEP",
            order=1,
            is_active=True,
        )
        other_form = FormDefinition.objects.create(
            workflow=other_workflow,
            name="Other Form",
            is_active=True,
        )
        other_section = FormSection.objects.create(
            form=other_form,
            name="Other Section",
            code="OTHER_DEPENDENT_OPTIONS_SECTION",
            order=1,
            is_active=True,
        )
        other_field = FormField.objects.create(
            section=other_section,
            name="Other Child",
            code="other_child",
            label="Other Child",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_parent_field=self.parent_field,
            order=0,
            is_active=True,
        )
        FieldAccess.objects.create(
            field=other_field,
            step=other_step,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        response = self.client.get(
            reverse("operator_panel:dependent_field_options"),
            {
                "instance_id": self.instance.pk,
                "field_id": other_field.pk,
                "parent_value": self.parent_item.value,
            },
        )

        self.assertEqual(response.status_code, 403)
