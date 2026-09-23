from types import SimpleNamespace

from django.test import SimpleTestCase

from workflow.operator_form_serializer import OperatorFormSerializer


class OperatorFormSerializerTests(SimpleTestCase):
    def test_row_serializes_normal_row_metadata_and_fields(self):
        field = SimpleNamespace(code="customer_name")

        result = OperatorFormSerializer.row(
            row_context={
                "row_id": "row-1",
                "row_order": 3,
                "parent_row_id": "parent-1",
                "fields": [
                    {
                        "field": field,
                        "can_edit": True,
                        "permission_can_edit": True,
                        "value": "Customer",
                        "display_value": "Customer",
                        "choices": [],
                        "parent_code": None,
                    }
                ],
                "child_groups": [],
            }
        )

        self.assertEqual(result["row_id"], "row-1")
        self.assertEqual(result["_id"], "row-1")
        self.assertEqual(result["row_order"], 3)
        self.assertEqual(result["parent_row_id"], "parent-1")
        self.assertEqual(result["fields"][0]["value"], "Customer")
        self.assertEqual(result["fields"][0]["field"], field)
        self.assertEqual(result["child_groups"], [])

    def test_row_serializes_nested_child_groups_recursively(self):
        parent_field = SimpleNamespace(code="parent_name")
        child_field = SimpleNamespace(code="child_name")

        result = OperatorFormSerializer.row(
            row_context={
                "row_id": "parent-1",
                "row_order": 0,
                "parent_row_id": None,
                "fields": [
                    {
                        "field": parent_field,
                        "can_edit": True,
                        "value": "Parent",
                    }
                ],
                "child_groups": [
                    {
                        "group": SimpleNamespace(code="children"),
                        "fields": [child_field],
                        "items": [
                            {
                                "row_id": "child-1",
                                "row_order": 2,
                                "parent_row_id": "parent-1",
                                "fields": [
                                    {
                                        "field": child_field,
                                        "can_edit": True,
                                        "value": "Child",
                                    }
                                ],
                                "child_groups": [],
                            }
                        ],
                        "permissions": {
                            "can_view": True,
                            "can_edit": True,
                            "can_add": True,
                            "can_delete": True,
                        },
                        "has_editable_fields": True,
                    }
                ],
            }
        )

        child_group = result["child_groups"][0]
        child_row = child_group["items"][0]

        self.assertEqual(child_group["group"].code, "children")
        self.assertEqual(child_row["row_id"], "child-1")
        self.assertEqual(child_row["row_order"], 2)
        self.assertEqual(child_row["parent_row_id"], "parent-1")
        self.assertEqual(child_row["fields"][0]["value"], "Child")

    def test_device_row_uses_same_row_contract_and_adds_device_context(self):
        field = SimpleNamespace(code="imei")
        device_model = SimpleNamespace(pk=42)

        result = OperatorFormSerializer.row(
            row_context={
                "row_id": "device-row-1",
                "row_order": 1,
                "parent_row_id": None,
                "fields": [
                    {
                        "field": field,
                        "can_edit": False,
                        "value": "123456789012345",
                    }
                ],
                "child_groups": [],
                "device": {
                    "instance_device_id": 101,
                    "device_id": 202,
                    "is_existing_device": True,
                    "device_model": device_model,
                    "device_type": "Phone",
                    "identifiers": [
                        {"type": "IMEI", "value": "123456789012345"}
                    ],
                    "reported_problem": "Broken screen",
                    "description": "Test device",
                    "warranty_status": "UNKNOWN",
                    "status": "RECEIVED",
                    "has_history": True,
                },
            }
        )

        self.assertEqual(result["row_id"], "device-row-1")
        self.assertEqual(result["_id"], "device-row-1")
        self.assertEqual(result["row_order"], 1)
        self.assertIsNone(result["parent_row_id"])

        self.assertEqual(result["instance_device_id"], 101)
        self.assertEqual(result["device_id"], 202)
        self.assertTrue(result["is_existing_device"])
        self.assertEqual(result["device_model_id"], 42)
        self.assertEqual(result["device_type"], "Phone")
        self.assertEqual(result["device_model"], str(device_model))
        self.assertEqual(result["identifiers"][0]["value"], "123456789012345")
        self.assertEqual(result["reported_problem"], "Broken screen")
        self.assertEqual(result["description"], "Test device")
        self.assertEqual(result["warranty_status"], "UNKNOWN")
        self.assertEqual(result["status"], "RECEIVED")
        self.assertTrue(result["has_history"])

    def test_normal_item_delegates_to_canonical_row_contract(self):
        field = SimpleNamespace(code="item_name")

        result = OperatorFormSerializer.normal_item(
            row_id="normal-1",
            row_order=4,
            parent_row_id="parent-1",
            field_contexts=[
                {
                    "field": field,
                    "can_edit": True,
                    "permission_can_edit": True,
                    "choices": [],
                }
            ],
            values={"item_name": "Item"},
            display_values={"item_name": "Item display"},
            child_groups=[],
        )

        self.assertEqual(result["row_id"], "normal-1")
        self.assertEqual(result["row_order"], 4)
        self.assertEqual(result["parent_row_id"], "parent-1")
        self.assertEqual(result["fields"][0]["value"], "Item")
        self.assertEqual(
            result["fields"][0]["display_value"],
            "Item display",
        )
