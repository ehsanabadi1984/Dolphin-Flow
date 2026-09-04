"""Runtime regression tests for Orange #2: dependent SELECT fields."""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from workflow.form_services import DynamicFormService
from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    LookupItem,
    LookupList,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)

User = get_user_model()


class Orange2DynamicSelectDependencyTests(TestCase):
    """Focused server-side/runtime coverage for SELECT dependencies."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="orange2_dep_user",
            password="test-password",
        )
        cls.other_user = User.objects.create_user(
            username="orange2_dep_other",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="Orange 2 Dependency Workflow",
            code="ORANGE2_DEP_WF",
            is_active=True,
        )
        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Orange 2 Step",
            code="ORANGE2_STEP",
            order=1,
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=cls.workflow,
            user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        cls.form = FormDefinition.objects.create(
            workflow=cls.workflow,
            name="Orange 2 Form",
            is_active=True,
        )
        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Main",
            code="ORANGE2_MAIN",
            order=1,
            is_active=True,
        )

        cls.lookup = LookupList.objects.create(
            name="Orange 2 Lookup",
            code="ORANGE2_LOOKUP",
            is_active=True,
        )
        cls.parent_a = LookupItem.objects.create(
            lookup_list=cls.lookup,
            value="a",
            label="Parent A",
            order=1,
            is_active=True,
        )
        cls.parent_b = LookupItem.objects.create(
            lookup_list=cls.lookup,
            value="b",
            label="Parent B",
            order=2,
            is_active=True,
        )
        LookupItem.objects.create(
            lookup_list=cls.lookup,
            parent=cls.parent_a,
            value="a1",
            label="Child A1",
            order=1,
            is_active=True,
        )
        LookupItem.objects.create(
            lookup_list=cls.lookup,
            parent=cls.parent_a,
            value="a2",
            label="Child A2",
            order=2,
            is_active=True,
        )
        LookupItem.objects.create(
            lookup_list=cls.lookup,
            parent=cls.parent_b,
            value="b1",
            label="Child B1",
            order=1,
            is_active=True,
        )

        cls.top_parent = FormField.objects.create(
            section=cls.section,
            name="Parent",
            code="parent",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=cls.lookup,
            label="Parent",
            order=1,
            is_active=True,
        )
        cls.top_child = FormField.objects.create(
            section=cls.section,
            name="Child",
            code="child",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=cls.lookup,
            choice_parent_field=cls.top_parent,
            label="Child",
            order=2,
            is_active=True,
        )

        cls.repeatable_section = FormSection.objects.create(
            form=cls.form,
            name="Repeatable",
            code="ORANGE2_REPEATABLE",
            order=2,
            is_active=True,
        )
        cls.group = FormRepeatableGroup.objects.create(
            section=cls.repeatable_section,
            name="Dependent Rows",
            code="dependent_rows",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            order=1,
            is_active=True,
        )
        cls.row_parent = FormField.objects.create(
            section=cls.repeatable_section,
            repeatable_group=cls.group,
            name="Row Parent",
            code="row_parent",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=cls.lookup,
            label="Row Parent",
            order=1,
            is_active=True,
        )
        cls.row_child = FormField.objects.create(
            section=cls.repeatable_section,
            repeatable_group=cls.group,
            name="Row Child",
            code="row_child",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=cls.lookup,
            choice_parent_field=cls.row_parent,
            label="Row Child",
            order=2,
            is_active=True,
        )
        cls.shared_group = FormRepeatableGroup.objects.create(
            section=cls.repeatable_section,
            name="Shared Parent Rows",
            code="shared_parent_rows",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            display_type=FormRepeatableGroup.DisplayType.LIST,
            order=2,
            is_active=True,
        )
        cls.shared_child = FormField.objects.create(
            section=cls.repeatable_section,
            repeatable_group=cls.shared_group,
            name="Shared Child",
            code="shared_child",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=cls.lookup,
            choice_parent_field=cls.top_parent,
            label="Shared Child",
            order=1,
            is_active=True,
        )

        for group in (cls.group, cls.shared_group):
            RepeatableGroupAccess.objects.create(
                group=group,
                step=cls.step,
                user=cls.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )

        for field in (
            cls.top_parent,
            cls.top_child,
            cls.row_parent,
            cls.row_child,
            cls.shared_child,
        ):
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                user=cls.user,
                can_view=True,
                can_edit=True,
            )

    def create_instance(self):
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            status=WorkflowInstance.Status.ACTIVE,
        )
        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=self.step,
            performed_by=self.user,
        )
        return instance

    @staticmethod
    def option_values(options):
        return [str(option["value"]) for option in options]

    def test_lookup_dependency_filters_child_by_parent(self):
        self.assertEqual(
            self.option_values(
                DynamicFormService._dependent_choices(self.top_child, "a")
            ),
            ["a1", "a2"],
        )
        self.assertEqual(
            self.option_values(
                DynamicFormService._dependent_choices(self.top_child, "b")
            ),
            ["b1"],
        )

    def test_blank_parent_has_no_child_options(self):
        self.assertEqual(
            DynamicFormService._dependent_choices(self.top_child, ""),
            [],
        )

    def test_same_repeatable_group_uses_same_row_parent(self):
        coherent_a, value_a = DynamicFormService._parent_value_for_field(
            self.row_child,
            raw_item={"row_parent": "a"},
        )
        coherent_b, value_b = DynamicFormService._parent_value_for_field(
            self.row_child,
            raw_item={"row_parent": "b"},
        )
        self.assertTrue(coherent_a)
        self.assertEqual(value_a, "a")
        self.assertTrue(coherent_b)
        self.assertEqual(value_b, "b")

    def test_top_level_parent_is_shared_with_repeatable_child(self):
        coherent, value = DynamicFormService._parent_value_for_field(
            self.shared_child,
            form_data={"parent": "a"},
        )
        self.assertTrue(coherent)
        self.assertEqual(value, "a")

    def test_saved_normal_rows_get_per_row_dependent_choices(self):
        instance = self.create_instance()
        FormData.objects.create(
            instance=instance,
            data={
                "dependent_rows": [
                    {"_id": "row-a", "row_parent": "a", "row_child": "a1"},
                    {"_id": "row-b", "row_parent": "b", "row_child": "b1"},
                ]
            },
        )
        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
        )
        group = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].code == "dependent_rows"
        )
        self.assertEqual(len(group["items"]), 2)
        first_child = next(
            field for field in group["items"][0]["fields"]
            if field["field"].code == "row_child"
        )
        second_child = next(
            field for field in group["items"][1]["fields"]
            if field["field"].code == "row_child"
        )
        self.assertEqual(
            self.option_values(first_child["choices"]),
            ["a1", "a2"],
        )
        self.assertEqual(
            self.option_values(second_child["choices"]),
            ["b1"],
        )

    def test_dependency_error_rejects_incompatible_child(self):
        error = DynamicFormService._dependency_error(
            self.top_child,
            parent_value="a",
            child_value="b1",
        )
        self.assertIsNotNone(error)

    def test_dependency_error_accepts_compatible_child(self):
        error = DynamicFormService._dependency_error(
            self.top_child,
            parent_value="a",
            child_value="a1",
        )
        self.assertIsNone(error)

    def test_dependency_error_rejects_child_when_parent_is_blank(self):
        error = DynamicFormService._dependency_error(
            self.top_child,
            parent_value="",
            child_value="a1",
        )
        self.assertIsNotNone(error)

    def test_dependency_options_endpoint_filters_results(self):
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        response = client.get(
            reverse("operator_panel:dependent_field_options"),
            {"field_id": self.top_child.pk, "parent_value": "a"},
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["options"],
            [
                {"value": "a1", "label": "Child A1"},
                {"value": "a2", "label": "Child A2"},
            ],
        )

    def test_dependency_options_endpoint_returns_empty_for_blank_parent(self):
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        response = client.get(
            reverse("operator_panel:dependent_field_options"),
            {"field_id": self.top_child.pk, "parent_value": ""},
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["options"], [])

    def test_dependency_options_endpoint_denies_non_member(self):
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.other_user)
        response = client.get(
            reverse("operator_panel:dependent_field_options"),
            {"field_id": self.top_child.pk, "parent_value": "a"},
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 403)

    def test_dependency_options_endpoint_ignores_non_dependent_field(self):
        client = Client(enforce_csrf_checks=False)
        client.force_login(self.user)
        response = client.get(
            reverse("operator_panel:dependent_field_options"),
            {"field_id": self.top_parent.pk, "parent_value": "a"},
            HTTP_HOST="localhost",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["options"], [])
