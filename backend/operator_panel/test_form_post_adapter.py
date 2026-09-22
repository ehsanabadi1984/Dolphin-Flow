from django.http import QueryDict
from django.test import TestCase

from operator_panel.form_post_adapter import OperatorPanelFormPostAdapter
from workflow.models import FormDefinition, FormField, FormRepeatableGroup, FormSection, Workflow


class FormPostAdapterTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(name="Adapter Workflow", code="ADAPTER_WF")
        self.form = FormDefinition.objects.create(workflow=self.workflow, name="Adapter Form")
        self.section = FormSection.objects.create(
            form=self.form, name="Adapter Section", code="ADAPTER_SECTION", order=1,
        )
        FormField.objects.create(
            section=self.section, name="Name", code="name", label="Name",
            field_type=FormField.FieldType.TEXT,
        )
        self.group = FormRepeatableGroup.objects.create(
            section=self.section, name="Items", code="items",
            group_type=FormRepeatableGroup.GroupType.NORMAL, order=1,
        )
        FormField.objects.create(
            section=self.section, repeatable_group=self.group,
            name="Title", code="title", label="Title",
            field_type=FormField.FieldType.TEXT,
        )
        FormField.objects.create(
            section=self.section, repeatable_group=self.group,
            name="Enabled", code="enabled", label="Enabled",
            field_type=FormField.FieldType.BOOLEAN,
        )

    def test_adapts_normal_field_and_repeatable_rows(self):
        post = QueryDict("", mutable=True)
        post.update({
            "name": "Ehsan",
            "items_0_title": "First",
            "items_1_title": "Second",
            "items_1__id": "12",
        })

        payload = OperatorPanelFormPostAdapter.adapt(form=self.form, submitted_data=post)

        self.assertEqual(payload, {
            "name": "Ehsan",
            "items": [
                {"title": "First"},
                {"title": "Second", "row_id": 12},
            ],
        })

    def test_omitted_normal_field_and_group_remain_omitted(self):
        post = QueryDict("", mutable=True)
        post["name"] = "Ehsan"

        payload = OperatorPanelFormPostAdapter.adapt(form=self.form, submitted_data=post)

        self.assertEqual(payload, {"name": "Ehsan"})

    def test_new_row_uuid_is_treated_as_create(self):
        post = QueryDict("", mutable=True)
        post.update({
            "items_0_title": "New",
            "items_0__id": "c43e58e0-8c7f-403f-b1e6-02469b448f02",
        })

        payload = OperatorPanelFormPostAdapter.adapt(form=self.form, submitted_data=post)

        self.assertEqual(payload["items"], [{"title": "New", "row_id": None}])

    def test_boolean_values_are_normalized(self):
        post = QueryDict("", mutable=True)
        post.setlist("items_0_enabled", ["false", "on"])
        post.setlist("items_1_enabled", ["false"])

        payload = OperatorPanelFormPostAdapter.adapt(form=self.form, submitted_data=post)

        self.assertEqual(payload["items"], [
            {"enabled": True},
            {"enabled": False},
        ])

    def test_repeatable_group_with_no_rows_is_not_created_from_missing_post_keys(self):
        post = QueryDict("", mutable=True)
        post["name"] = "Ehsan"

        payload = OperatorPanelFormPostAdapter.adapt(form=self.form, submitted_data=post)

        self.assertNotIn("items", payload)
