from datetime import date

from django.test import TestCase
from django.template.loader import render_to_string

from workflow.form_services import DynamicFormService
from workflow.models import (
    DeviceModel,
    DeviceType,
    FieldAccess,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    RepeatableGroupAccess,
    RepeatableRow,
    RepeatableRowValue,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)


class DeviceJalaliDateRenderingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="device_jalali_date_test_user",
            password="test-password",
        )
        cls.workflow = Workflow.objects.create(
            name="DEVICE Jalali Date Test",
            code="DEVICE_JALALI_DATE_TEST",
            is_active=True,
        )
        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Step One",
            code="STEP_ONE",
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
            name="Device Form",
            is_active=True,
        )
        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Devices",
            code="DEVICES",
            order=1,
            is_active=True,
        )
        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Devices",
            code="devices",
            order=1,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            display_type=FormRepeatableGroup.DisplayType.TABLE,
            is_active=True,
        )
        RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

        cls.imei_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="IMEI",
            code="imei",
            system_key=FormField.SystemKey.IMEI,
            field_type=FormField.FieldType.TEXT,
            label="IMEI",
            order=1,
            is_required=True,
            is_active=True,
        )
        cls.date_field = FormField.objects.create(
            section=cls.section,
            repeatable_group=cls.group,
            name="Warranty Date",
            code="warranty_date",
            field_type=FormField.FieldType.DATE,
            calendar=FormField.Calendar.JALALI,
            label="تاریخ گارانتی",
            order=2,
            is_active=True,
        )
        for field in (cls.imei_field, cls.date_field):
            FieldAccess.objects.create(
                field=field,
                step=cls.step,
                role=WorkflowMembership.Role.EXECUTOR,
                can_view=True,
                can_edit=True,
            )

        cls.device_type = DeviceType.objects.create(
            name="Test Phone",
            code="DEVICE_JALALI_TEST_PHONE",
            is_active=True,
        )
        cls.device_model = DeviceModel.objects.create(
            device_type=cls.device_type,
            brand="Test",
            name="Test Model",
            code="DEVICE_JALALI_TEST_MODEL",
            is_active=True,
        )

    def test_persisted_device_date_renders_jalali_in_flat_table(self):
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

        instance_device = InstanceDevice.objects.create(
            instance=instance,
            draft_imei="123456789012345",
            draft_device_model=self.device_model,
            draft_device_type=self.device_type,
        )
        row = RepeatableRow.objects.create(
            instance=instance,
            group=self.group,
            row_order=0,
            instance_device=instance_device,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=self.date_field,
            date_value=date(2026, 9, 27),
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=False,
        )
        group_context = next(
            group
            for section in result["sections"]
            for group in section["repeatable_groups"]
            if group["group"].pk == self.group.pk
        )
        item = group_context["items"][0]
        date_context = next(
            field
            for field in item["fields"]
            if field["field"].pk == self.date_field.pk
        )

        self.assertEqual(date_context["value"], "۱۴۰۵/۰۷/۰۵")
        self.assertEqual(date_context["display_value"], "۱۴۰۵/۰۷/۰۵")

        request = self.client.get("/").wsgi_request
        request.user = self.user
        html = render_to_string(
            "operator_panel/workflow_instance.html",
            {
                "instance": instance,
                "transitions": [],
                "dynamic_form": result,
                "edit_mode": False,
                "can_view_device_history": False,
                "validation_errors": [],
                "page_title": self.workflow.name,
                "page_breadcrumb": self.workflow.name,
            },
            request=request,
        )

        self.assertIn(
            "۱۴۰۵/۰۷/۰۵",
            html,
        )
        self.assertNotIn(
            "2026-09-27",
            html,
        )
