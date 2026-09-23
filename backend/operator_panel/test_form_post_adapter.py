from django.http import QueryDict
from django.test import TestCase

from operator_panel.form_post_adapter import OperatorPanelFormPostAdapter
from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    RepeatableRow,
    Workflow,
    WorkflowInstance,
)


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
            order=0,
        )
        FormField.objects.create(
            section=self.section, repeatable_group=self.group,
            name="Enabled", code="enabled", label="Enabled",
            field_type=FormField.FieldType.BOOLEAN,
            order=1,
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

    def test_normal_boolean_values_are_normalized(self):
        post = QueryDict("", mutable=True)
        post.setlist("enabled_normal", ["false", "on"])

        boolean_field = FormField.objects.create(
            section=self.section,
            name="Normal Enabled",
            code="enabled_normal",
            label="Normal Enabled",
            field_type=FormField.FieldType.BOOLEAN,
            order=2,
        )

        payload = OperatorPanelFormPostAdapter.adapt(
            form=self.form,
            submitted_data=post,
        )

        self.assertTrue(payload["enabled_normal"])

        post.setlist("enabled_normal", ["false"])
        payload = OperatorPanelFormPostAdapter.adapt(
            form=self.form,
            submitted_data=post,
        )

        self.assertFalse(payload["enabled_normal"])

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


    def test_adapts_nested_repeatable_rows_into_child_groups(self):
        child_group = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=self.group,
            name="Child Items",
            code="child_items",
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            order=2,
        )
        FormField.objects.create(
            section=self.section,
            repeatable_group=child_group,
            name="Child Title",
            code="child_title",
            label="Child Title",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )

        post = QueryDict("", mutable=True)
        post.update({
            "items_0_title": "Parent",
            "items_0_child_items_0_child_title": "First child",
            "items_0_child_items_1_child_title": "Second child",
            "items_0_child_items_1__id": "21",
        })

        payload = OperatorPanelFormPostAdapter.adapt(
            form=self.form,
            submitted_data=post,
        )

        self.assertEqual(
            payload["items"],
            [
                {
                    "title": "Parent",
                    "child_groups": {
                        "child_items": (
                            {
                                "child_title": "First child",
                            },
                            {
                                "child_title": "Second child",
                                "row_id": 21,
                            },
                        ),
                    },
                },
            ],
        )


    def test_existing_device_instance_id_is_resolved_to_repeatable_row_id(self):
        device_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            code="devices",
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            order=2,
        )
        FormField.objects.create(
            section=self.section,
            repeatable_group=device_group,
            name="Label",
            code="label",
            label="Label",
            field_type=FormField.FieldType.TEXT,
            order=0,
        )
        instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )
        instance_device = InstanceDevice.objects.create(
            instance=instance,
        )
        row = RepeatableRow.objects.create(
            instance=instance,
            group=device_group,
            instance_device=instance_device,
            row_order=0,
        )

        post = QueryDict("", mutable=True)
        post.update({
            "devices_0_label": "Existing device",
            "devices_0_instance_device_id": str(instance_device.pk),
        })

        payload = OperatorPanelFormPostAdapter.adapt(
            form=self.form,
            submitted_data=post,
            instance=instance,
        )

        self.assertEqual(
            payload["devices"],
            [
                {
                    "label": "Existing device",
                    "row_id": row.pk,
                }
            ],
        )
