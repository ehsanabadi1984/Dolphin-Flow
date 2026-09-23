from django.test import TestCase

from accounts.models import User
from workflow.history_browser_service import HistoryBrowserService
from workflow.history_permissions import HISTORY_ACTION
from workflow.models import (
    Device,
    DeviceModel,
    DeviceType,
    FieldAccess,
    RepeatableGroupAccess,
    FormDefinition,
    FormField,
    FormSection,
    FormRepeatableGroup,
    InstanceDevice,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
)


class HistoryBrowserServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="history-browser-user",
            password="test-password",
        )
        self.workflow = Workflow.objects.create(
            name="History Browser Workflow",
            code="HISTORY_BROWSER",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Repair",
            code="REPAIR",
            order=1,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
            current_step=self.step,
            started_by=self.user,
        )

    def _execution(self, snapshot):
        return WorkflowStepExecution.objects.create(
            instance=self.instance,
            workflow_step=self.step,
            performed_by=self.user,
            is_submitted=True,
            data={"history": snapshot},
        )

    def test_history_permission_is_independent_from_view(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self._execution({"version": 1, "fields": [], "repeatable_groups": []})

        self.assertEqual(
            HistoryBrowserService.get_history(
                user=self.user,
                instance_id=self.instance.pk,
            ),
            [],
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self.assertEqual(
            len(
                HistoryBrowserService.get_history(
                    user=self.user,
                    instance_id=self.instance.pk,
                )
            ),
            1,
        )

    def test_history_filters_top_level_fields_by_current_field_permission(self):
        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="History Form",
        )
        section = FormSection.objects.create(
            form=form,
            name="Main",
            code="MAIN",
            order=1,
        )
        visible_field = FormField.objects.create(
            section=section,
            name="Customer",
            code="customer",
            label="Customer",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        hidden_field = FormField.objects.create(
            section=section,
            name="Internal Note",
            code="internal_note",
            label="Internal Note",
            field_type=FormField.FieldType.TEXT,
            order=2,
        )
        FieldAccess.objects.create(
            field=visible_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )
        FieldAccess.objects.create(
            field=hidden_field,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=False,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self._execution({
            "version": 1,
            "fields": [
                {"code": visible_field.code, "label": visible_field.label, "value": "Ehsan"},
                {"code": hidden_field.code, "label": hidden_field.label, "value": "Secret"},
            ],
            "repeatable_groups": [],
        })

        history = HistoryBrowserService.get_history(
            user=self.user,
            instance_id=self.instance.pk,
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(
            [field["code"] for field in history[0]["snapshot"]["fields"]],
            [visible_field.code],
        )

    def test_history_filters_repeatable_groups_by_current_group_permission(self):
        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="History Form",
        )
        section = FormSection.objects.create(
            form=form,
            name="Main",
            code="MAIN",
            order=1,
        )
        visible_group = FormRepeatableGroup.objects.create(
            section=section,
            name="Visible Items",
            code="visible_items",
            order=1,
        )
        hidden_group = FormRepeatableGroup.objects.create(
            section=section,
            name="Hidden Items",
            code="hidden_items",
            order=2,
        )
        RepeatableGroupAccess.objects.create(
            group=visible_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )
        RepeatableGroupAccess.objects.create(
            group=hidden_group,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=False,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self._execution({
            "version": 1,
            "fields": [],
            "repeatable_groups": [
                {
                    "code": visible_group.code,
                    "name": visible_group.name,
                    "items": [{"row_id": 1, "fields": []}],
                },
                {
                    "code": hidden_group.code,
                    "name": hidden_group.name,
                    "items": [{"row_id": 2, "fields": []}],
                },
            ],
        })

        history = HistoryBrowserService.get_history(
            user=self.user,
            instance_id=self.instance.pk,
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(
            [group["code"] for group in history[0]["snapshot"]["repeatable_groups"]],
            [visible_group.code],
        )

    def test_history_filters_nested_groups_by_current_group_permission(self):
        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="History Form",
        )
        section = FormSection.objects.create(
            form=form,
            name="Main",
            code="MAIN",
            order=1,
        )
        parent_group = FormRepeatableGroup.objects.create(
            section=section,
            name="Parent Items",
            code="parent_items",
            order=1,
        )
        visible_child = FormRepeatableGroup.objects.create(
            section=section,
            parent_group=parent_group,
            name="Visible Child",
            code="visible_child",
            order=2,
        )
        hidden_child = FormRepeatableGroup.objects.create(
            section=section,
            parent_group=parent_group,
            name="Hidden Child",
            code="hidden_child",
            order=3,
        )
        RepeatableGroupAccess.objects.create(
            group=parent_group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )
        RepeatableGroupAccess.objects.create(
            group=visible_child,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )
        RepeatableGroupAccess.objects.create(
            group=hidden_child,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=False,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self._execution({
            "version": 1,
            "fields": [],
            "repeatable_groups": [{
                "code": parent_group.code,
                "name": parent_group.name,
                "items": [{
                    "row_id": 1,
                    "fields": [],
                    "child_groups": [
                        {
                            "code": visible_child.code,
                            "name": visible_child.name,
                            "items": [{"row_id": 11, "fields": []}],
                        },
                        {
                            "code": hidden_child.code,
                            "name": hidden_child.name,
                            "items": [{"row_id": 12, "fields": []}],
                        },
                    ],
                }],
            }],
        })

        history = HistoryBrowserService.get_history(
            user=self.user,
            instance_id=self.instance.pk,
        )

        self.assertEqual(len(history), 1)
        item = history[0]["snapshot"]["repeatable_groups"][0]["items"][0]
        self.assertEqual(
            [group["code"] for group in item["child_groups"]],
            [visible_child.code],
        )

    def test_history_filters_fields_inside_permitted_repeatable_group(self):
        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="History Form",
        )
        section = FormSection.objects.create(
            form=form,
            name="Main",
            code="MAIN",
            order=1,
        )
        group = FormRepeatableGroup.objects.create(
            section=section,
            name="Items",
            code="items",
            order=1,
        )
        visible_field = FormField.objects.create(
            section=section,
            repeatable_group=group,
            name="Visible",
            code="visible",
            label="Visible",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        hidden_field = FormField.objects.create(
            section=section,
            repeatable_group=group,
            name="Hidden",
            code="hidden",
            label="Hidden",
            field_type=FormField.FieldType.TEXT,
            order=2,
        )
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )
        FieldAccess.objects.create(
            field=visible_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )
        FieldAccess.objects.create(
            field=hidden_field,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=False,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self._execution({
            "version": 1,
            "fields": [],
            "repeatable_groups": [{
                "code": group.code,
                "name": group.name,
                "items": [{
                    "row_id": 1,
                    "fields": [
                        {"code": visible_field.code, "value": "Visible value"},
                        {"code": hidden_field.code, "value": "Secret value"},
                    ],
                }],
            }],
        })

        history = HistoryBrowserService.get_history(
            user=self.user,
            instance_id=self.instance.pk,
        )

        self.assertEqual(len(history), 1)
        fields = history[0]["snapshot"]["repeatable_groups"][0]["items"][0]["fields"]
        self.assertEqual(
            [field["code"] for field in fields],
            [visible_field.code],
        )

    def test_history_shows_field_with_edit_permission_even_without_view_permission(self):
        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="History Form",
        )
        section = FormSection.objects.create(
            form=form,
            name="Main",
            code="MAIN",
            order=1,
        )
        field = FormField.objects.create(
            section=section,
            name="Editable",
            code="editable",
            label="Editable",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self._execution({
            "version": 1,
            "fields": [{
                "code": field.code,
                "value": "Editable value",
            }],
            "repeatable_groups": [],
        })

        history = HistoryBrowserService.get_history(
            user=self.user,
            instance_id=self.instance.pk,
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(
            [item["code"] for item in history[0]["snapshot"]["fields"]],
            [field.code],
        )

    def test_history_shows_repeatable_group_with_edit_permission_even_without_view_permission(self):
        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="History Form",
        )
        section = FormSection.objects.create(
            form=form,
            name="Main",
            code="MAIN",
            order=1,
        )
        group = FormRepeatableGroup.objects.create(
            section=section,
            name="Editable Items",
            code="editable_items",
            order=1,
        )
        field = FormField.objects.create(
            section=section,
            repeatable_group=group,
            name="Value",
            code="value",
            label="Value",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )
        RepeatableGroupAccess.objects.create(
            group=group,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self._execution({
            "version": 1,
            "fields": [],
            "repeatable_groups": [{
                "code": group.code,
                "name": group.name,
                "items": [{
                    "row_id": 1,
                    "fields": [{
                        "code": field.code,
                        "value": "Editable group value",
                    }],
                }],
            }],
        })

        history = HistoryBrowserService.get_history(
            user=self.user,
            instance_id=self.instance.pk,
        )

        self.assertEqual(len(history), 1)
        groups = history[0]["snapshot"]["repeatable_groups"]
        self.assertEqual([item["code"] for item in groups], [group.code])
        self.assertEqual(
            [item["code"] for item in groups[0]["items"][0]["fields"]],
            [field.code],
        )

    def test_device_filter_keeps_complete_top_level_history(self):
        device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Brand",
            name="Model X",
            code="MODEL_X",
        )
        device = Device.objects.create(device_model=device_model)
        InstanceDevice.objects.create(
            instance=self.instance,
            device=device,
            is_active=True,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step,
            user=self.user,
            action=HISTORY_ACTION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        self._execution(
            {
                "version": 1,
                "fields": [
                    {
                        "code": "customer",
                        "label": "Customer",
                        "display_label": "Customer",
                        "value": "Ehsan",
                        "display_value": "Ehsan",
                    }
                ],
                "repeatable_groups": [
                    {
                        "code": "devices",
                        "name": "Devices",
                        "items": [
                            {
                                "device_id": device.pk,
                                "instance_device_id": 1,
                                "fields": [],
                            },
                            {
                                "device_id": 999999,
                                "instance_device_id": 2,
                                "fields": [],
                            },
                        ],
                    }
                ],
            }
        )

        history = HistoryBrowserService.get_history(
            user=self.user,
            device_id=device.pk,
        )

        self.assertEqual(len(history), 1)
        self.assertEqual(
            history[0]["snapshot"]["fields"][0]["value"],
            "Ehsan",
        )
        self.assertEqual(
            history[0]["snapshot"]["repeatable_groups"][0]["items"][0]["device_id"],
            device.pk,
        )
