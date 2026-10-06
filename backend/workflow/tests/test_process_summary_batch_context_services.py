from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from workflow.models import (
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableRow,
    Workflow,
    WorkflowInstance,
)
from workflow.process_summary_batch_context_services import ProcessSummaryBatchContextService


class ProcessSummaryBatchContextServiceTests(TestCase):
    def make_workflow(self, code):
        workflow = Workflow.objects.create(name=code, code=code)
        form = FormDefinition.objects.create(workflow=workflow, name=f"{code} Form")
        section = FormSection.objects.create(
            form=form,
            name="Main",
            code=f"{code}_MAIN",
            order=1,
        )
        return workflow, form, section

    def test_build_separates_instances_and_workflows_and_batches_reads(self):
        workflow_a, form_a, section_a = self.make_workflow("SUMMARY_BATCH_A")
        workflow_b, form_b, section_b = self.make_workflow("SUMMARY_BATCH_B")

        field_a = FormField.objects.create(
            section=section_a,
            name="Name A",
            code="name_a",
            label="Name A",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        group_a = FormRepeatableGroup.objects.create(
            section=section_a,
            name="Items A",
            code="items_a",
            order=1,
        )
        FormField.objects.create(
            section=section_a,
            repeatable_group=group_a,
            name="Value A",
            code="value_a",
            label="Value A",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        group_b = FormRepeatableGroup.objects.create(
            section=section_b,
            name="Items B",
            code="items_b",
            order=1,
        )

        instance_a = WorkflowInstance.objects.create(workflow=workflow_a)
        instance_a2 = WorkflowInstance.objects.create(workflow=workflow_a)
        instance_b = WorkflowInstance.objects.create(workflow=workflow_b)
        FormData.objects.create(instance=instance_a, data={"name_a": "A1"})
        FormData.objects.create(instance=instance_a2, data={"name_a": "A2"})
        FormData.objects.create(instance=instance_b, data={"other": "B"})

        row_a = RepeatableRow.objects.create(instance=instance_a, group=group_a)
        row_a2 = RepeatableRow.objects.create(instance=instance_a2, group=group_a)
        row_b = RepeatableRow.objects.create(instance=instance_b, group=group_b)

        with CaptureQueriesContext(connection) as captured:
            context = ProcessSummaryBatchContextService.build(
                instances=[instance_a, instance_a2, instance_b],
            )

        self.assertEqual(context["forms"][workflow_a.pk], form_a)
        self.assertEqual(context["forms"][workflow_b.pk], form_b)
        self.assertEqual(context["form_data"][instance_a.pk], {"name_a": "A1"})
        self.assertEqual(context["form_data"][instance_a2.pk], {"name_a": "A2"})
        self.assertEqual(context["form_data"][instance_b.pk], {"other": "B"})
        self.assertEqual(
            context["rows"][(instance_a.pk, group_a.pk, None)],
            [row_a],
        )
        self.assertEqual(
            context["rows"][(instance_a2.pk, group_a.pk, None)],
            [row_a2],
        )
        self.assertEqual(
            context["rows"][(instance_b.pk, group_b.pk, None)],
            [row_b],
        )

        form_data_queries = [
            query["sql"]
            for query in captured.captured_queries
            if 'from "workflow_formdata"' in query["sql"].lower()
        ]
        repeatable_row_queries = [
            query["sql"]
            for query in captured.captured_queries
            if 'from "workflow_repeatablerow"' in query["sql"].lower()
        ]
        self.assertEqual(len(form_data_queries), 1)
        self.assertEqual(len(repeatable_row_queries), 1)

    def test_build_preserves_nested_row_parent_context(self):
        workflow, form, section = self.make_workflow("SUMMARY_BATCH_NESTED")
        parent_group = FormRepeatableGroup.objects.create(
            section=section,
            name="Parents",
            code="parents",
            order=1,
        )
        child_group = FormRepeatableGroup.objects.create(
            section=section,
            parent_group=parent_group,
            name="Children",
            code="children",
            order=2,
        )
        instance = WorkflowInstance.objects.create(workflow=workflow)
        parent = RepeatableRow.objects.create(instance=instance, group=parent_group)
        child = RepeatableRow.objects.create(
            instance=instance,
            group=child_group,
            parent_row=parent,
        )

        context = ProcessSummaryBatchContextService.build(instances=[instance])

        self.assertEqual(
            context["rows"][(instance.pk, parent_group.pk, None)],
            [parent],
        )
        self.assertEqual(
            context["rows"][(instance.pk, child_group.pk, parent.pk)],
            [child],
        )
