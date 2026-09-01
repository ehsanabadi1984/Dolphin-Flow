from django.test import TestCase
from workflow.models import Workflow


class WorkflowCodeAutoGenerationTests(TestCase):
    """Regression tests for automatic Workflow.code generation.

    Workflow.code must never be saved as an empty string.
    It must be auto-generated when not explicitly provided.
    """

    def test_create_workflow_without_code_generates_unique_code(self):
        wf = Workflow.objects.create(name="Auto Code Test 1")
        self.assertIsNotNone(wf.code)
        self.assertNotEqual(wf.code, "")
        self.assertTrue(wf.code.startswith("WF_"))
        self.assertEqual(len(wf.code), 11)  # "WF_" + 8 hex chars

    def test_create_multiple_workflows_get_unique_codes(self):
        wf1 = Workflow.objects.create(name="Auto Code Test 2")
        wf2 = Workflow.objects.create(name="Auto Code Test 3")
        self.assertNotEqual(wf1.code, wf2.code)
        self.assertTrue(wf1.code.startswith("WF_"))
        self.assertTrue(wf2.code.startswith("WF_"))

    def test_explicit_code_is_preserved(self):
        wf = Workflow.objects.create(
            name="Explicit Code Test",
            code="MY_CUSTOM_CODE",
        )
        self.assertEqual(wf.code, "MY_CUSTOM_CODE")

    def test_empty_string_code_generates_auto_code(self):
        wf = Workflow.objects.create(name="Empty Code Test", code="")
        self.assertNotEqual(wf.code, "")
        self.assertTrue(wf.code.startswith("WF_"))

    def test_code_is_unique_across_workflows(self):
        codes = set()
        for i in range(50):
            wf = Workflow.objects.create(name=f"Unique Test {i}")
            codes.add(wf.code)
        self.assertEqual(len(codes), 50, "All 50 generated codes must be unique")
