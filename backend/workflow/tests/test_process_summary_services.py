from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from workflow.models import (
    FieldAccess,
    FormData,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableGroupAccess,
    RepeatableRow,
    RepeatableRowValue,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
)
from workflow.process_summary_services import ProcessSummaryService


User = get_user_model()


class ProcessSummaryServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="process_summary_user",
            password="test-password",
        )
        cls.workflow = Workflow.objects.create(
            name="Process Summary Test",
            code="PROCESS_SUMMARY_TEST",
        )
        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step One",
            code="SUMMARY_STEP",
            order=1,
        )
        WorkflowMembership.objects.create(
            workflow=cls.workflow,
            user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        cls.form = FormDefinition.objects.create(
            workflow=cls.workflow,
            name="Summary Form",
        )
        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Main",
            code="MAIN",
            order=1,
        )
        cls.instance = WorkflowInstance.objects.create(
            workflow=cls.workflow,
            current_step=cls.step,
        )

    def allow_field(self, field):
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

    def allow_group(self, group):
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

    def test_normal_field_returns_display_value(self):
        field = FormField.objects.create(
            section=self.section,
            name="Name",
            code="name",
            field_type=FormField.FieldType.TEXT,
            label="نام",
            show_in_process_summary=True,
        )
        self.allow_field(field)
        FormData.objects.create(
            instance=self.instance,
            data={"name": "علی"},
        )

        self.assertEqual(
            ProcessSummaryService.get_for_instance(
                instance=self.instance,
                user=self.user,
            ),
            [{"label": "نام", "value": "علی"}],
        )

    def test_disabled_summary_flag_is_excluded(self):
        field = FormField.objects.create(
            section=self.section,
            name="Internal",
            code="internal",
            field_type=FormField.FieldType.TEXT,
            label="داخلی",
            show_in_process_summary=False,
        )
        self.allow_field(field)
        FormData.objects.create(
            instance=self.instance,
            data={"internal": "secret"},
        )

        self.assertEqual(
            ProcessSummaryService.get_for_instance(
                instance=self.instance,
                user=self.user,
            ),
            [],
        )

    def test_hidden_field_is_excluded(self):
        field = FormField.objects.create(
            section=self.section,
            name="Private",
            code="private",
            field_type=FormField.FieldType.TEXT,
            label="خصوصی",
            show_in_process_summary=True,
        )
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=False,
            can_edit=False,
        )
        FormData.objects.create(
            instance=self.instance,
            data={"private": "secret"},
        )

        self.assertEqual(
            ProcessSummaryService.get_for_instance(
                instance=self.instance,
                user=self.user,
            ),
            [],
        )

    def test_repeatable_rows_keep_row_context(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parts",
            label="قطعات",
            code="parts",
            order=1,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Part",
            code="part",
            field_type=FormField.FieldType.TEXT,
            label="قطعه",
            show_in_process_summary=True,
        )
        self.allow_group(group)
        self.allow_field(field)

        row_one = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        row_two = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=1,
        )
        RepeatableRowValue.objects.create(
            row=row_one,
            field=field,
            text_value="A",
        )
        RepeatableRowValue.objects.create(
            row=row_two,
            field=field,
            text_value="B",
        )

        result = ProcessSummaryService.get_for_instance(
            instance=self.instance,
            user=self.user,
        )

        self.assertEqual(
            result[0],
            {
                "group_label": "قطعات",
                "rows": [
                    {
                        "row_id": row_one.pk,
                        "items": [{"label": "قطعه", "value": "A"}],
                        "children": [],
                    },
                    {
                        "row_id": row_two.pk,
                        "items": [{"label": "قطعه", "value": "B"}],
                        "children": [],
                    },
                ],
            },
        )

    def test_nested_repeatable_preserves_parent_child_context(self):
        parent = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Parent",
            label="والد",
            code="parent",
            order=1,
        )
        child = FormRepeatableGroup.objects.create(
            section=self.section,
            parent_group=parent,
            name="Child",
            label="فرزند",
            code="child",
            order=2,
        )
        parent_field = FormField.objects.create(
            section=self.section,
            repeatable_group=parent,
            name="Parent Field",
            code="parent_field",
            field_type=FormField.FieldType.TEXT,
            label="والد",
            show_in_process_summary=True,
        )
        child_field = FormField.objects.create(
            section=self.section,
            repeatable_group=child,
            name="Child Field",
            code="child_field",
            field_type=FormField.FieldType.TEXT,
            label="فرزند",
            show_in_process_summary=True,
        )
        self.allow_group(parent)
        self.allow_group(child)
        self.allow_field(parent_field)
        self.allow_field(child_field)

        parent_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=parent,
            row_order=0,
        )
        child_row = RepeatableRow.objects.create(
            instance=self.instance,
            group=child,
            parent_row=parent_row,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=parent_row,
            field=parent_field,
            text_value="P",
        )
        RepeatableRowValue.objects.create(
            row=child_row,
            field=child_field,
            text_value="C",
        )

        result = ProcessSummaryService.get_for_instance(
            instance=self.instance,
            user=self.user,
        )

        self.assertEqual(
            result[0]["rows"][0]["items"],
            [{"label": "والد", "value": "P"}],
        )
        self.assertEqual(
            result[0]["rows"][0]["children"][0]["rows"][0]["items"],
            [{"label": "فرزند", "value": "C"}],
        )

    def test_repeatable_model_select_is_batch_resolved(self):
        from workflow.models import DeviceModel, DeviceType

        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Models",
            label="مدل‌ها",
            code="models",
            order=1,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="Model",
            code="model",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=ContentType.objects.get_for_model(DeviceModel),
            choice_value_field="code",
            choice_label_field="name",
            label="مدل",
            show_in_process_summary=True,
        )
        self.allow_group(group)
        self.allow_field(field)

        device_type = DeviceType.objects.create(
            name="Phone",
            code="SUMMARY_MODEL_PHONE",
        )
        model_a = DeviceModel.objects.create(
            device_type=device_type,
            brand="Brand",
            name="Model A",
            code="SUMMARY_MODEL_A",
        )
        model_b = DeviceModel.objects.create(
            device_type=device_type,
            brand="Brand",
            name="Model B",
            code="SUMMARY_MODEL_B",
        )

        row_a = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        row_b = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=1,
        )
        RepeatableRowValue.objects.create(
            row=row_a,
            field=field,
            reference_id=model_a.code,
        )
        RepeatableRowValue.objects.create(
            row=row_b,
            field=field,
            reference_id=model_b.code,
        )

        with CaptureQueriesContext(connection) as queries:
            result = ProcessSummaryService.get_for_instance(
                instance=self.instance,
                user=self.user,
            )

        model_queries = [
            query
            for query in queries
            if DeviceModel._meta.db_table in query["sql"]
        ]

        self.assertEqual(len(model_queries), 1)
        self.assertEqual(
            result[0]["rows"][0]["items"],
            [{"label": "مدل", "value": "Model A"}],
        )
        self.assertEqual(
            result[0]["rows"][1]["items"],
            [{"label": "مدل", "value": "Model B"}],
        )

    def test_repeatable_device_system_field_uses_read_service(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Devices",
            label="دستگاه‌ها",
            code="devices",
            order=1,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
        )
        field = FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name="IMEI",
            code="imei",
            field_type=FormField.FieldType.TEXT,
            system_key=FormField.SystemKey.IMEI,
            label="IMEI",
            show_in_process_summary=True,
        )
        self.allow_group(group)
        self.allow_field(field)

        from workflow.models import DeviceModel, DeviceType, InstanceDevice

        device_type = DeviceType.objects.create(
            name="Phone",
            code="SUMMARY_PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Brand",
            name="Model",
            code="SUMMARY_MODEL",
        )
        instance_device = InstanceDevice.objects.create(
            instance=self.instance,
            draft_imei="123456",
            draft_device_model=device_model,
            draft_device_type=device_type,
        )
        RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
            instance_device=instance_device,
        )

        result = ProcessSummaryService.get_for_instance(
            instance=self.instance,
            user=self.user,
        )

        self.assertEqual(
            result[0]["rows"][0]["items"],
            [{"label": "IMEI", "value": "123456"}],
        )
