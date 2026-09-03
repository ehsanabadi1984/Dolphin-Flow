from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.template.loader import get_template
from django.test import RequestFactory, TestCase

from workflow.form_services import DynamicFormService
from workflow.models import (
    Device,
    DeviceIdentifier,
    DeviceModel,
    DeviceType,
    FieldAccess,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    InstanceDevice,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)

User = get_user_model()


class DeviceGroupConfigurationTests(TestCase):
    """
    A DEVICE repeatable group is an independent workflow component:

        DEVICE GROUP
            |
      +-----+-----+-----+
      |     |     |     |
    IMEI  MODEL  TYPE  (no fields)

    Its rendering must not depend on IMEI/DeviceModel FormFields, and
    unidentified devices must be persistable with Type + Model (no IMEI)
    or with Type only (no IMEI, no Model).
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="device_group_config_test",
            password="test-password",
        )

        cls.device_type = DeviceType.objects.create(
            name="Test Phone",
            code="TEST_PHONE",
            is_active=True,
        )

        cls.device_model = DeviceModel.objects.create(
            device_type=cls.device_type,
            brand="Test Brand",
            name="Test Model",
            code="TEST_MODEL",
            is_active=True,
        )

        cls.device_model_2 = DeviceModel.objects.create(
            device_type=cls.device_type,
            brand="Other Brand",
            name="Other Model",
            code="OTHER_MODEL",
            is_active=True,
        )

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    @classmethod
    def _build_workflow(cls, code, system_keys=()):
        """
        Build a workflow whose DEVICE group contains FormFields for
        the given system keys (in order). An empty tuple produces a
        DEVICE group with no FormFields at all.
        """
        workflow = Workflow.objects.create(
            name=f"{code} WF",
            code=code,
            is_active=True,
        )

        step = WorkflowStep.objects.create(
            workflow=workflow,
            name="Step",
            code="STEP",
            order=1,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=workflow,
            user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        form = FormDefinition.objects.create(
            workflow=workflow,
            name="Repair Form",
            is_active=True,
        )

        section = FormSection.objects.create(
            form=form,
            name="Device Info",
            code="DEVICE_INFO",
            order=1,
            is_active=True,
        )

        group = FormRepeatableGroup.objects.create(
            section=section,
            name="Devices",
            code="devices",
            order=1,
            group_type=FormRepeatableGroup.GroupType.DEVICE,
            is_active=True,
        )

        field_specs = {
            FormField.SystemKey.IMEI: ("imei", FormField.FieldType.TEXT, False),
            FormField.SystemKey.DEVICE_TYPE: (
                "device_type",
                FormField.FieldType.SELECT,
                True,
            ),
            FormField.SystemKey.DEVICE_MODEL: (
                "device_model_id",
                FormField.FieldType.SELECT,
                True,
            ),
        }

        for order, system_key in enumerate(system_keys, start=1):
            code_name, field_type, is_required = field_specs[system_key]

            field = FormField.objects.create(
                section=section,
                repeatable_group=group,
                name=code_name,
                code=code_name,
                field_type=field_type,
                system_key=system_key,
                label=code_name,
                order=order,
                is_required=is_required,
                is_active=True,
            )

            FieldAccess.objects.create(
                field=field,
                step=step,
                user=cls.user,
                can_view=True,
                can_edit=True,
            )

        RepeatableGroupAccess.objects.create(
            group=group,
            step=step,
            user=cls.user,
            can_view=True,
            can_edit=True,
            can_add=True,
        )

        return workflow, step, form, group

    @classmethod
    def _create_instance(cls, workflow, step):
        instance = WorkflowInstance.objects.create(
            workflow=workflow,
            current_step=step,
            status=WorkflowInstance.Status.ACTIVE,
        )

        WorkflowStepExecution.objects.create(
            instance=instance,
            workflow_step=step,
            performed_by=cls.user,
        )

        return instance

    @staticmethod
    def _get_group(result, code="devices"):
        for section in result["sections"]:
            for group in section["repeatable_groups"]:
                if group["group"].code == code:
                    return group
        return None

    def _render_template(self, *, instance, dynamic_form, edit_mode):
        request = RequestFactory().get("/")
        request.user = self.user

        context = {
            "instance": instance,
            "dynamic_form": dynamic_form,
            "edit_mode": edit_mode,
            "transitions": [],
            "error": None,
            "validation_errors": [],
            "has_saved_data": False,
            "current_step_execution": None,
        }

        return get_template(
            "operator_panel/workflow_instance.html"
        ).render(context, request)

    # ---------------------------------------------------------------
    # Device Group rendering
    # ---------------------------------------------------------------

    def test_config1_imei_model_fields_rendered(self):
        """DEVICE group with IMEI + Type + Model fields is rendered."""
        workflow, step, _, _ = self._build_workflow(
            "CFG1",
            system_keys=(
                FormField.SystemKey.IMEI,
                FormField.SystemKey.DEVICE_TYPE,
                FormField.SystemKey.DEVICE_MODEL,
            ),
        )

        instance = self._create_instance(workflow, step)

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        group = self._get_group(result)

        self.assertIsNotNone(group)

        system_keys = {
            field_info["field"].system_key
            for field_info in group["fields"]
        }

        self.assertIn(FormField.SystemKey.IMEI, system_keys)
        self.assertIn(FormField.SystemKey.DEVICE_TYPE, system_keys)
        self.assertIn(FormField.SystemKey.DEVICE_MODEL, system_keys)

    def test_config2_type_model_fields_rendered(self):
        """DEVICE group with Type + Model (no IMEI) is rendered."""
        workflow, step, _, _ = self._build_workflow(
            "CFG2",
            system_keys=(
                FormField.SystemKey.DEVICE_TYPE,
                FormField.SystemKey.DEVICE_MODEL,
            ),
        )

        instance = self._create_instance(workflow, step)

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        group = self._get_group(result)

        self.assertIsNotNone(group)

        system_keys = {
            field_info["field"].system_key
            for field_info in group["fields"]
        }

        self.assertNotIn(FormField.SystemKey.IMEI, system_keys)
        self.assertIn(FormField.SystemKey.DEVICE_TYPE, system_keys)
        self.assertIn(FormField.SystemKey.DEVICE_MODEL, system_keys)

    def test_config3_type_only_field_rendered(self):
        """DEVICE group with only a Type field is rendered."""
        workflow, step, _, _ = self._build_workflow(
            "CFG3",
            system_keys=(FormField.SystemKey.DEVICE_TYPE,),
        )

        instance = self._create_instance(workflow, step)

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        group = self._get_group(result)

        self.assertIsNotNone(group)

        self.assertEqual(len(group["fields"]), 1)
        self.assertEqual(
            group["fields"][0]["field"].system_key,
            FormField.SystemKey.DEVICE_TYPE,
        )

    def test_config4_no_fields_group_rendered(self):
        """DEVICE group with no FormFields is still rendered."""
        workflow, step, _, _ = self._build_workflow("CFG4")

        instance = self._create_instance(workflow, step)

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        group = self._get_group(result)

        self.assertIsNotNone(group)
        self.assertEqual(group["fields"], [])
        self.assertTrue(group["can_view"])
        self.assertTrue(group["can_add"])

        # A group with can_add but no fields must still count as
        # editable so the operator can re-enter edit mode.
        self.assertTrue(group["has_editable_fields"])

    def test_add_device_ui_available_without_fields(self):
        """
        The Add Device button and the Device Modal are rendered for a
        field-less DEVICE group when the group permissions allow it.
        """
        workflow, step, _, _ = self._build_workflow("CFG4")

        instance = self._create_instance(workflow, step)

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        html = self._render_template(
            instance=instance,
            dynamic_form=result,
            edit_mode=True,
        )

        self.assertIn("+ افزودن دستگاه", html)
        self.assertIn('data-device-modal="devices"', html)

    # ---------------------------------------------------------------
    # Submission / persistence
    # ---------------------------------------------------------------

    def test_identified_device_with_imei_continues_to_work(self):
        """Case A: Type + Model + IMEI links to an existing Device."""
        workflow, step, _, _ = self._build_workflow(
            "CFG1",
            system_keys=(
                FormField.SystemKey.IMEI,
                FormField.SystemKey.DEVICE_TYPE,
                FormField.SystemKey.DEVICE_MODEL,
            ),
        )

        device = Device.objects.create(device_model=self.device_model)

        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="111111111111111",
        )

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_imei": "111111111111111",
                "devices_0_device_type": str(self.device_type.pk),
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)

        self.assertEqual(instance_device.device_id, device.pk)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model)

    def test_unidentified_type_model_no_imei_persisted(self):
        """Case B: Type + Model, no IMEI, is persisted as a draft."""
        workflow, step, _, _ = self._build_workflow(
            "CFG2",
            system_keys=(
                FormField.SystemKey.DEVICE_TYPE,
                FormField.SystemKey.DEVICE_MODEL,
            ),
        )

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_device_type": str(self.device_type.pk),
                "devices_0_device_model_id": str(self.device_model.pk),
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)

        self.assertIsNone(instance_device.device)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertEqual(
            instance_device.draft_device_model_id,
            self.device_model.pk,
        )
        self.assertEqual(
            instance_device.draft_device_type_id,
            self.device_type.pk,
        )

    def test_unidentified_type_only_persisted(self):
        """Case C: Type only (no IMEI, no Model) is persisted."""
        workflow, step, _, _ = self._build_workflow(
            "CFG3",
            system_keys=(FormField.SystemKey.DEVICE_TYPE,),
        )

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_device_type": str(self.device_type.pk),
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)

        self.assertIsNone(instance_device.device)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model)
        self.assertEqual(
            instance_device.draft_device_type_id,
            self.device_type.pk,
        )

    def test_no_device_created_for_type_only(self):
        workflow, step, _, _ = self._build_workflow(
            "CFG3",
            system_keys=(FormField.SystemKey.DEVICE_TYPE,),
        )

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_device_type": str(self.device_type.pk),
            },
        )

        self.assertEqual(Device.objects.count(), 0)

    def test_no_device_identifier_created_for_type_only(self):
        workflow, step, _, _ = self._build_workflow(
            "CFG3",
            system_keys=(FormField.SystemKey.DEVICE_TYPE,),
        )

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_device_type": str(self.device_type.pk),
            },
        )

        self.assertEqual(DeviceIdentifier.objects.count(), 0)

    def test_device_type_preserved_for_type_only(self):
        """
        The selected DeviceType survives both persistence and the
        GET rendering used by the Device Modal.
        """
        workflow, step, _, _ = self._build_workflow(
            "CFG3",
            system_keys=(FormField.SystemKey.DEVICE_TYPE,),
        )

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_device_type": str(self.device_type.pk),
            },
        )

        result = DynamicFormService.get_form_for_step(
            instance=instance,
            user=self.user,
            edit_mode=True,
        )

        group = self._get_group(result)

        self.assertIsNotNone(group)
        self.assertEqual(len(group["items"]), 1)

        item = group["items"][0]

        self.assertEqual(item["device_type"], self.device_type.name)

        type_field_info = item["fields"][0]

        self.assertEqual(
            type_field_info["field"].system_key,
            FormField.SystemKey.DEVICE_TYPE,
        )
        self.assertEqual(
            str(type_field_info["value"]),
            str(self.device_type.pk),
        )
        self.assertEqual(
            type_field_info["display_value"],
            self.device_type.name,
        )

    def test_two_type_only_devices_remain_independent(self):
        workflow, step, _, _ = self._build_workflow(
            "CFG3",
            system_keys=(FormField.SystemKey.DEVICE_TYPE,),
        )

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_device_type": str(self.device_type.pk),
                "devices_1_device_type": str(self.device_type.pk),
            },
        )

        instance_devices = list(
            InstanceDevice.objects.filter(instance=instance).order_by("pk")
        )

        self.assertEqual(len(instance_devices), 2)
        self.assertNotEqual(
            instance_devices[0].pk,
            instance_devices[1].pk,
        )

        for instance_device in instance_devices:
            self.assertIsNone(instance_device.device)
            self.assertEqual(
                instance_device.draft_device_type_id,
                self.device_type.pk,
            )

    def test_field_less_group_blank_row_persisted(self):
        """
        A DEVICE group without FormFields can still persist rows
        (fully unidentified devices) without error.
        """
        workflow, step, _, _ = self._build_workflow("CFG4")

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_instance_device_id": "",
            },
        )

        instance_device = InstanceDevice.objects.get(instance=instance)

        self.assertIsNone(instance_device.device)
        self.assertEqual(instance_device.draft_imei, "")
        self.assertIsNone(instance_device.draft_device_model)
        self.assertIsNone(instance_device.draft_device_type)

        self.assertEqual(Device.objects.count(), 0)
        self.assertEqual(DeviceIdentifier.objects.count(), 0)

    # ---------------------------------------------------------------
    # Regression tests
    # ---------------------------------------------------------------

    def test_imei_lookup_reuse_across_instances_unchanged(self):
        workflow, step, _, _ = self._build_workflow(
            "CFG1",
            system_keys=(
                FormField.SystemKey.IMEI,
                FormField.SystemKey.DEVICE_TYPE,
                FormField.SystemKey.DEVICE_MODEL,
            ),
        )

        device = Device.objects.create(device_model=self.device_model)

        DeviceIdentifier.objects.create(
            device=device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="222222222222222",
        )

        instance_1 = self._create_instance(workflow, step)
        instance_2 = self._create_instance(workflow, step)

        for instance in (instance_1, instance_2):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "devices_0_imei": "222222222222222",
                    "devices_0_device_type": str(self.device_type.pk),
                    "devices_0_device_model_id": str(self.device_model.pk),
                },
            )

        self.assertEqual(
            InstanceDevice.objects.get(instance=instance_1).device_id,
            device.pk,
        )
        self.assertEqual(
            InstanceDevice.objects.get(instance=instance_2).device_id,
            device.pk,
        )

    def test_imei_model_mismatch_still_rejected(self):
        workflow, step, _, _ = self._build_workflow(
            "CFG1",
            system_keys=(
                FormField.SystemKey.IMEI,
                FormField.SystemKey.DEVICE_TYPE,
                FormField.SystemKey.DEVICE_MODEL,
            ),
        )

        DeviceIdentifier.objects.create(
            device=Device.objects.create(device_model=self.device_model),
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="333333333333333",
        )

        instance = self._create_instance(workflow, step)

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "devices_0_imei": "333333333333333",
                    "devices_0_device_type": str(self.device_type.pk),
                    "devices_0_device_model_id": str(
                        self.device_model_2.pk
                    ),
                },
            )

    def test_type_model_mismatch_still_rejected(self):
        """
        When both DeviceType and DeviceModel are submitted, they must
        be consistent.
        """
        other_type = DeviceType.objects.create(
            name="Test Tablet",
            code="TEST_TABLET",
            is_active=True,
        )

        workflow, step, _, _ = self._build_workflow(
            "CFG2",
            system_keys=(
                FormField.SystemKey.DEVICE_TYPE,
                FormField.SystemKey.DEVICE_MODEL,
            ),
        )

        instance = self._create_instance(workflow, step)

        with self.assertRaises(ValidationError):
            DynamicFormService.save_form_for_step(
                instance=instance,
                user=self.user,
                submitted_data={
                    "devices_0_device_type": str(other_type.pk),
                    "devices_0_device_model_id": str(self.device_model.pk),
                },
            )

    def test_existing_draft_with_blank_imei_does_not_resolve(self):
        """
        An existing draft with a blank draft_imei (Type-only) must
        never resolve to an existing Device on re-save.
        """
        identified_device = Device.objects.create(
            device_model=self.device_model,
        )

        DeviceIdentifier.objects.create(
            device=identified_device,
            identifier_type=DeviceIdentifier.IdentifierType.IMEI,
            value="444444444444444",
        )

        workflow, step, _, _ = self._build_workflow(
            "CFG3",
            system_keys=(FormField.SystemKey.DEVICE_TYPE,),
        )

        instance = self._create_instance(workflow, step)

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_device_type": str(self.device_type.pk),
            },
        )

        draft = InstanceDevice.objects.get(instance=instance)

        self.assertIsNone(draft.device)

        # Re-submit the same draft row.
        DynamicFormService.save_form_for_step(
            instance=instance,
            user=self.user,
            submitted_data={
                "devices_0_instance_device_id": str(draft.pk),
                "devices_0_device_type": str(self.device_type.pk),
            },
        )

        draft.refresh_from_db()

        self.assertIsNone(draft.device)
        self.assertEqual(draft.draft_imei, "")
        self.assertEqual(
            draft.draft_device_type_id,
            self.device_type.pk,
        )