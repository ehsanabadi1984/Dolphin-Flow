from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
import threading

from workflow.history_models import HistoryConfiguration, HistoryField
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
    Notification,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)
from workflow.form_draft_save_services import FormDraftSaveService
from workflow.services import WorkflowExecutionService


User = get_user_model()


class WorkflowExecutionTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="auth_exec_user",
            password="test-password",
        )

        self.destination_user = User.objects.create_user(
            username="auth_exec_destination",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Authorization Execution Test",
            code="AUTH_EXEC_TEST",
            is_active=True,
        )

        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step One",
            code="AUTH_EXEC_STEP_ONE",
            order=1,
            is_active=True,
        )

        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step Two",
            code="AUTH_EXEC_STEP_TWO",
            order=2,
            is_active=True,
        )

        self.step_three = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Test Step Three",
            code="AUTH_EXEC_STEP_THREE",
            order=3,
            is_active=True,
        )

        self.transition_one = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Test Transition One",
            code="AUTH_EXEC_TRANSITION_ONE",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )

        self.transition_two = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Test Transition Two",
            code="AUTH_EXEC_TRANSITION_TWO",
            from_step=self.step_two,
            to_step=self.step_three,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.destination_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

    def grant_execute_permission(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def grant_start_permission(self):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def grant_transition_permission(self, transition):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=transition,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def start_instance(self):
        return WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )

    def grant_step_action_permission(self, *, user, step, action_code):
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=step,
            user=user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code=action_code,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def test_allow(self):
        self.grant_execute_permission()
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        instance = self.start_instance()

        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        instance.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )

    def _create_repeatable_form(
        self,
        *,
        required_child=False,
    ):
        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Repeatable Execution Form",
            is_active=True,
        )
        section = FormSection.objects.create(
            form=form,
            name="Repeatable Section",
            code="REPEATABLE_SECTION",
            order=1,
            is_active=True,
        )
        group = FormRepeatableGroup.objects.create(
            section=section,
            name="Items",
            code="items",
            order=1,
            group_type=FormRepeatableGroup.GroupType.NORMAL,
            is_active=True,
        )
        field = FormField.objects.create(
            section=section,
            repeatable_group=group,
            name="Item Name",
            code="item_name",
            field_type=FormField.FieldType.TEXT,
            label="Item Name",
            order=1,
            is_active=True,
            is_required=True,
        )

        child_group = None
        child_field = None
        if required_child:
            child_group = FormRepeatableGroup.objects.create(
                section=section,
                parent_group=group,
                name="Children",
                code="children",
                order=2,
                group_type=FormRepeatableGroup.GroupType.NORMAL,
                is_active=True,
                is_required=True,
            )
            child_field = FormField.objects.create(
                section=section,
                repeatable_group=child_group,
                name="Child Name",
                code="child_name",
                field_type=FormField.FieldType.TEXT,
                label="Child Name",
                order=1,
                is_active=True,
                is_required=True,
            )

        for current_group in [group, child_group]:
            if current_group is None:
                continue
            RepeatableGroupAccess.objects.create(
                group=current_group,
                step=self.step_one,
                user=self.user,
                can_view=True,
                can_edit=True,
                can_add=True,
                can_delete=True,
            )

        for current_field in [field, child_field]:
            if current_field is None:
                continue
            FieldAccess.objects.create(
                field=current_field,
                step=self.step_one,
                user=self.user,
                can_view=True,
                can_edit=True,
            )

        history_configuration = HistoryConfiguration.objects.create(
            form=form,
            name="Repeatable Execution History",
            is_active=True,
        )
        HistoryField.objects.create(
            configuration=history_configuration,
            form_field=field,
            display_label=field.label,
            display_order=1,
            is_enabled=True,
        )
        if child_field is not None:
            HistoryField.objects.create(
                configuration=history_configuration,
                form_field=child_field,
                display_label=child_field.label,
                display_order=2,
                is_enabled=True,
            )

        return form, group, field, child_group, child_field

    def test_repeatable_draft_flows_through_transition_submit_and_history(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        form, group, field, child_group, child_field = (
            self._create_repeatable_form(
                required_child=True,
            )
        )

        instance = self.start_instance()

        FormDraftSaveService.save(
            instance=instance,
            step=self.step_one,
            user=self.user,
            submitted_data={
                "items": [
                    {
                        "item_name": "Parent",
                        "children": [
                            {"child_name": "Child"},
                        ],
                    }
                ],
            },
            edit_mode=True,
        )

        parent_row = RepeatableRow.objects.get(
            instance=instance,
            group=group,
        )
        child_row = RepeatableRow.objects.get(
            instance=instance,
            group=child_group,
            parent_row=parent_row,
        )

        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=parent_row,
                field=field,
            ).text_value,
            "Parent",
        )
        self.assertEqual(
            RepeatableRowValue.objects.get(
                row=child_row,
                field=child_field,
            ).text_value,
            "Child",
        )

        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        instance.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_two.pk)
        self.assertTrue(
            WorkflowStepExecution.objects.get(
                instance=instance,
                workflow_step=self.step_one,
            ).is_submitted
        )
        self.assertTrue(
            WorkflowTransitionExecution.objects.filter(
                pk=transition_execution.pk,
                instance=instance,
                transition=self.transition_one,
            ).exists()
        )

        snapshot = (
            WorkflowStepExecution.objects.get(
                instance=instance,
                workflow_step=self.step_one,
            ).data["history"]
        )
        history_by_code = {
            group_snapshot["code"]: group_snapshot
            for group_snapshot in snapshot["repeatable_groups"]
        }
        self.assertEqual(
            history_by_code["items"]["items"][0]["fields"][0]["value"],
            "Parent",
        )
        self.assertEqual(
            history_by_code["items"]["items"][0]["child_groups"][0]["items"][0]["fields"][0]["value"],
            "Child",
        )

    def test_transition_submit_reads_canonical_repeatable_rows(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        form, group, field, child_group, child_field = (
            self._create_repeatable_form(
                required_child=True,
            )
        )

        instance = self.start_instance()

        # Draft save intentionally allows an incomplete tree. Submit must
        # validate the canonical relational state instead of the old payload.
        FormDraftSaveService.save(
            instance=instance,
            step=self.step_one,
            user=self.user,
            submitted_data={
                "items": [
                    {"item_name": "Parent"},
                ],
            },
            edit_mode=True,
        )

        parent_row = RepeatableRow.objects.get(
            instance=instance,
            group=group,
        )
        self.assertFalse(
            RepeatableRow.objects.filter(
                instance=instance,
                group=child_group,
            ).exists()
        )

        with self.assertRaises(ValidationError):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_one.pk)
        self.assertFalse(
            WorkflowStepExecution.objects.get(
                instance=instance,
                workflow_step=self.step_one,
            ).is_submitted
        )
        self.assertFalse(
            WorkflowTransitionExecution.objects.filter(
                instance=instance,
                transition=self.transition_one,
            ).exists()
        )
        self.assertTrue(
            RepeatableRow.objects.filter(
                pk=parent_row.pk,
            ).exists()
        )

    def test_submit_valid_form_advances_workflow_and_stores_history(self):
        self.grant_execute_permission()
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Execution Submit Form",
            is_active=True,
        )

        section = FormSection.objects.create(
            form=form,
            name="Main Section",
            code="MAIN",
            order=1,
            is_active=True,
        )

        field = FormField.objects.create(
            section=section,
            name="Customer Name",
            code="customer_name",
            field_type=FormField.FieldType.TEXT,
            label="Customer Name",
            is_required=True,
            order=1,
            is_active=True,
        )

        FieldAccess.objects.create(
            field=field,
            step=self.step_one,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        history_configuration = HistoryConfiguration.objects.create(
            form=form,
            name="Execution History",
            is_active=True,
        )

        HistoryField.objects.create(
            configuration=history_configuration,
            form_field=field,
            display_label="Customer Name",
            display_order=1,
            is_enabled=True,
        )

        instance = self.start_instance()

        FormData.objects.create(
            instance=instance,
            data={
                "customer_name": "Ehsan",
            },
        )

        step_execution = WorkflowStepExecution.objects.get(
            instance=instance,
            workflow_step=self.step_one,
        )

        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        instance.refresh_from_db()
        step_execution.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )

        self.assertIsNotNone(
            transition_execution,
        )

        self.assertTrue(
            step_execution.is_submitted,
        )

        self.assertIsNotNone(
            step_execution.submitted_at,
        )

        self.assertIn(
            "history",
            step_execution.data,
        )

        history = step_execution.data["history"]

        self.assertEqual(
            history["version"],
            1,
        )

        self.assertEqual(
            len(history["fields"]),
            1,
        )

        self.assertEqual(
            history["fields"][0]["code"],
            "customer_name",
        )

        self.assertEqual(
            history["fields"][0]["value"],
            "Ehsan",
        )

        self.assertTrue(
            WorkflowTransitionExecution.objects.filter(
                pk=transition_execution.pk,
                instance=instance,
                transition=self.transition_one,
            ).exists()
        )

        self.assertTrue(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_two,
            ).exists()
        )

    def test_submit_invalid_form_does_not_advance_workflow_or_store_history(self):
        self.grant_execute_permission()
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Invalid Submit Form",
            is_active=True,
        )

        section = FormSection.objects.create(
            form=form,
            name="Main Section",
            code="MAIN",
            order=1,
            is_active=True,
        )

        field = FormField.objects.create(
            section=section,
            name="Customer Name",
            code="customer_name",
            field_type=FormField.FieldType.TEXT,
            label="Customer Name",
            is_required=True,
            order=1,
            is_active=True,
        )

        FieldAccess.objects.create(
            field=field,
            step=self.step_one,
            user=self.user,
            can_view=True,
            can_edit=True,
        )

        instance = self.start_instance()

        FormData.objects.create(
            instance=instance,
            data={
                "customer_name": "",
            },
        )

        step_execution = WorkflowStepExecution.objects.get(
            instance=instance,
            workflow_step=self.step_one,
        )

        with self.assertRaises(ValidationError):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()
        step_execution.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_one.pk,
        )

        self.assertFalse(
            step_execution.is_submitted,
        )

        self.assertIsNone(
            step_execution.submitted_at,
        )

        self.assertNotIn(
            "history",
            step_execution.data,
        )

        self.assertFalse(
            WorkflowTransitionExecution.objects.filter(
                instance=instance,
                transition=self.transition_one,
            ).exists()
        )

        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_two,
            ).exists()
        )

    def test_deny(self):
        self.grant_execute_permission()
        self.grant_start_permission()

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.transition_one,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.DENY,
        )

        instance = self.start_instance()

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_one.pk,
        )

    def test_no_permission(self):
        self.grant_execute_permission()
        self.grant_start_permission()

        instance = self.start_instance()

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_one.pk,
        )

    def test_execute_permission_alone_does_not_authorize_transition(self):
        """EXECUTE is task/action capability, not transition mutation permission."""
        self.grant_execute_permission()
        self.grant_start_permission()

        instance = self.start_instance()

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()
        self.assertEqual(
            instance.current_step_id,
            self.step_one.pk,
        )

    def test_transition_permission_works_without_execute_permission(self):
        """TRANSITION authorizes mutation independently from EXECUTE."""
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        instance = self.start_instance()

        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        instance.refresh_from_db()
        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )

    def test_assigned_to_does_not_grant_transition_permission(self):
        """Step assignment is routing, not authorization."""
        self.grant_start_permission()
        self.step_one.assigned_to = self.user
        self.step_one.save(update_fields=["assigned_to"])

        instance = self.start_instance()

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=self.transition_one,
                user=self.user,
            )

        instance.refresh_from_db()
        self.assertEqual(
            instance.current_step_id,
            self.step_one.pk,
        )

    def test_transition_permission_does_not_require_step_assignment(self):
        """A user may execute an authorized transition when not assigned to the step."""
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        self.step_one.assigned_to = self.destination_user
        self.step_one.save(update_fields=["assigned_to"])

        instance = self.start_instance()

        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        instance.refresh_from_db()
        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )

    def test_acceptance_transition_stays_pending_at_source_step(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)
        self.grant_transition_permission(self.transition_two)

        self.transition_two.requires_acceptance = True
        self.transition_two.save(update_fields=["requires_acceptance"])

        instance = self.start_instance()

        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        # Move to step two using the normal transition first.
        instance.refresh_from_db()
        self.assertEqual(instance.current_step_id, self.step_two.pk)

        # The acceptance-required transition is then executed from step two.
        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_two,
            user=self.user,
        )

        instance.refresh_from_db()
        transition_execution.refresh_from_db()

        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )
        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )
        self.assertFalse(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_three,
            ).exists()
        )

    def _create_pending_acceptance_execution(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)
        self.grant_transition_permission(self.transition_two)

        self.transition_two.requires_acceptance = True
        self.transition_two.reject_to_step = self.step_one
        self.transition_two.save(
            update_fields=[
                "requires_acceptance",
                "reject_to_step",
            ]
        )

        instance = self.start_instance()
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )
        return WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_two,
            user=self.user,
        )

    def test_acceptance_transition_notifies_unique_accept_reject_recipients(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)
        self.grant_transition_permission(self.transition_two)

        self.transition_two.requires_acceptance = True
        self.transition_two.reject_to_step = self.step_one
        self.transition_two.save(
            update_fields=[
                "requires_acceptance",
                "reject_to_step",
            ]
        )

        third_user = User.objects.create_user(
            username="acceptance_notification_third",
            password="test-password",
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=third_user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        self.grant_step_action_permission(
            user=self.destination_user,
            step=self.step_three,
            action_code="ACCEPT",
        )
        self.grant_step_action_permission(
            user=self.destination_user,
            step=self.step_three,
            action_code="REJECT",
        )
        self.grant_step_action_permission(
            user=third_user,
            step=self.step_three,
            action_code="REJECT",
        )

        instance = self.start_instance()
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )
        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_two,
            user=self.user,
        )

        notifications = Notification.objects.filter(
            workflow_instance=instance,
            transition_execution=transition_execution,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
        )

        self.assertEqual(notifications.count(), 2)
        self.assertEqual(
            set(notifications.values_list("recipient_id", flat=True)),
            {self.destination_user.pk, third_user.pk},
        )
        self.assertTrue(
            notifications.filter(
                workflow_step=self.step_three,
                title="نیاز به تأیید دریافت",
            ).exists()
        )

    def test_acceptance_transition_does_not_notify_users_without_step_action_permission(self):
        transition_execution = self._create_pending_acceptance_execution()

        notifications = Notification.objects.filter(
            transition_execution=transition_execution,
            notification_type=Notification.NotificationType.ACTION_REQUIRED,
        )

        self.assertEqual(notifications.count(), 0)

    def test_normal_transition_does_not_create_acceptance_notification(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        self.grant_step_action_permission(
            user=self.destination_user,
            step=self.step_two,
            action_code="ACCEPT",
        )

        instance = self.start_instance()
        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        self.assertFalse(
            Notification.objects.filter(
                transition_execution=transition_execution,
                notification_type=Notification.NotificationType.ACTION_REQUIRED,
                title="نیاز به تأیید دریافت",
            ).exists()
        )

    def test_acceptance_notification_rolls_back_with_pending_transition(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)
        self.grant_transition_permission(self.transition_two)

        self.transition_two.requires_acceptance = True
        self.transition_two.save(update_fields=["requires_acceptance"])

        self.grant_step_action_permission(
            user=self.destination_user,
            step=self.step_three,
            action_code="ACCEPT",
        )

        instance = self.start_instance()
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        from unittest.mock import patch

        with patch(
            "workflow.services.NotificationService.create",
            side_effect=RuntimeError("notification failure"),
        ):
            with self.assertRaises(RuntimeError):
                WorkflowExecutionService.execute_transition(
                    instance=instance,
                    transition=self.transition_two,
                    user=self.user,
                )

        instance.refresh_from_db()

        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )
        self.assertFalse(
            WorkflowTransitionExecution.objects.filter(
                instance=instance,
                transition=self.transition_two,
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                workflow_instance=instance,
                notification_type=Notification.NotificationType.ACTION_REQUIRED,
                title="نیاز به تأیید دریافت",
            ).exists()
        )

    def test_acceptance_notification_is_linked_to_pending_transition(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)
        self.grant_transition_permission(self.transition_two)

        self.transition_two.requires_acceptance = True
        self.transition_two.save(update_fields=["requires_acceptance"])

        self.grant_step_action_permission(
            user=self.destination_user,
            step=self.step_three,
            action_code="ACCEPT",
        )

        instance = self.start_instance()
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )
        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_two,
            user=self.user,
        )

        notification = Notification.objects.get(
            recipient=self.destination_user,
            transition_execution=transition_execution,
        )

        self.assertEqual(
            notification.workflow_instance_id,
            instance.pk,
        )
        self.assertEqual(
            notification.workflow_step_id,
            self.step_three.pk,
        )
        self.assertEqual(
            notification.notification_type,
            Notification.NotificationType.ACTION_REQUIRED,
        )

    def test_accept_transition_execution_resolves_pending_transition(self):
        transition_execution = self._create_pending_acceptance_execution()

        self.grant_step_action_permission(
            user=self.destination_user,
            step=self.step_three,
            action_code="ACCEPT",
        )

        resolved = WorkflowExecutionService.accept_transition_execution(
            transition_execution=transition_execution,
            user=self.destination_user,
        )

        instance = WorkflowInstance.objects.get(pk=transition_execution.instance_id)
        resolved.refresh_from_db()

        self.assertEqual(
            resolved.status,
            WorkflowTransitionExecution.Status.ACCEPTED,
        )
        self.assertEqual(resolved.accepted_by_id, self.destination_user.pk)
        self.assertIsNone(resolved.rejected_by_id)
        self.assertEqual(instance.current_step_id, self.step_three.pk)

        destination_execution = WorkflowStepExecution.objects.get(
            instance=instance,
            workflow_step=self.step_three,
        )
        self.assertEqual(
            destination_execution.performed_by_id,
            self.destination_user.pk,
        )

    def test_reject_transition_execution_returns_to_configured_step(self):
        transition_execution = self._create_pending_acceptance_execution()

        self.grant_step_action_permission(
            user=self.destination_user,
            step=self.step_three,
            action_code="REJECT",
        )

        resolved = WorkflowExecutionService.reject_transition_execution(
            transition_execution=transition_execution,
            user=self.destination_user,
        )

        instance = WorkflowInstance.objects.get(pk=transition_execution.instance_id)
        resolved.refresh_from_db()

        self.assertEqual(
            resolved.status,
            WorkflowTransitionExecution.Status.REJECTED,
        )
        self.assertIsNone(resolved.accepted_by_id)
        self.assertEqual(resolved.rejected_by_id, self.destination_user.pk)
        self.assertEqual(instance.current_step_id, self.step_one.pk)

        returned_execution = WorkflowStepExecution.objects.filter(
            instance=instance,
            workflow_step=self.step_one,
        ).order_by("-performed_at").first()
        self.assertEqual(
            returned_execution.performed_by_id,
            self.destination_user.pk,
        )
        self.assertFalse(returned_execution.is_submitted)

    def test_accept_transition_execution_requires_accept_permission(self):
        transition_execution = self._create_pending_acceptance_execution()

        with self.assertRaises(PermissionDenied):
            WorkflowExecutionService.accept_transition_execution(
                transition_execution=transition_execution,
                user=self.destination_user,
            )

        transition_execution.refresh_from_db()
        instance = WorkflowInstance.objects.get(pk=transition_execution.instance_id)

        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.PENDING,
        )
        self.assertIsNone(transition_execution.accepted_by_id)
        self.assertIsNone(transition_execution.rejected_by_id)
        self.assertEqual(instance.current_step_id, self.step_two.pk)

    def test_normal_transition_remains_accepted_and_advances(self):
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        instance = self.start_instance()

        transition_execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        instance.refresh_from_db()
        transition_execution.refresh_from_db()

        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.ACCEPTED,
        )
        self.assertEqual(
            instance.current_step_id,
            self.step_two.pk,
        )
        self.assertTrue(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_two,
            ).exists()
        )

    def test_transition_creates_notification_for_destination_executors(self):
        self.grant_execute_permission()
        self.grant_start_permission()
        self.grant_transition_permission(self.transition_one)

        # Assign destination step to a different user
        self.step_two.assigned_to = self.destination_user
        self.step_two.save(update_fields=["assigned_to"])

        instance = self.start_instance()

        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )

        notification = Notification.objects.get(
            recipient=self.destination_user,
            workflow_instance=instance,
            workflow_step=self.step_two,
        )

        self.assertEqual(
            notification.notification_type,
            Notification.NotificationType.ACTION_REQUIRED,
        )

        self.assertIsNotNone(
            notification.transition_execution,
        )

        self.assertFalse(
            notification.is_read,
        )


class WorkflowExecutionConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = User.objects.create_user(
            username="concurrency_sender",
            password="test-password",
        )
        self.accept_user_one = User.objects.create_user(
            username="concurrency_accept_one",
            password="test-password",
        )
        self.accept_user_two = User.objects.create_user(
            username="concurrency_accept_two",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Concurrency Acceptance Test",
            code="CONCURRENCY_ACCEPT_TEST",
            is_active=True,
        )
        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Concurrency Step One",
            code="CONCURRENCY_STEP_ONE",
            order=1,
            is_active=True,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Concurrency Step Two",
            code="CONCURRENCY_STEP_TWO",
            order=2,
            is_active=True,
        )
        self.step_three = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Concurrency Step Three",
            code="CONCURRENCY_STEP_THREE",
            order=3,
            is_active=True,
        )
        self.transition_one = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Concurrency Transition One",
            code="CONCURRENCY_TRANSITION_ONE",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )
        self.transition_two = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Concurrency Acceptance Transition",
            code="CONCURRENCY_ACCEPTANCE_TRANSITION",
            from_step=self.step_two,
            to_step=self.step_three,
            is_active=True,
            requires_acceptance=True,
            reject_to_step=self.step_one,
        )

        for user in (
            self.user,
            self.accept_user_one,
            self.accept_user_two,
        ):
            WorkflowMembership.objects.create(
                workflow=self.workflow,
                user=user,
                role=WorkflowMembership.Role.EXECUTOR,
                is_active=True,
            )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.user,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.transition_one,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.transition_two,
            user=self.user,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        for user in (self.accept_user_one, self.accept_user_two):
            WorkflowPermission.objects.create(
                workflow=self.workflow,
                step=self.step_three,
                user=user,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="ACCEPT",
                effect=WorkflowPermission.Effect.ALLOW,
            )
            WorkflowPermission.objects.create(
                workflow=self.workflow,
                step=self.step_three,
                user=user,
                action=WorkflowPermission.Action.STEP_ACTION,
                action_code="REJECT",
                effect=WorkflowPermission.Effect.ALLOW,
            )

    def _create_pending_acceptance_execution(self):
        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.user,
        )
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.user,
        )
        return WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_two,
            user=self.user,
        )

    def _run_two_actions(self, first_action, second_action):
        barrier = threading.Barrier(2)
        results = []
        results_lock = threading.Lock()

        def worker(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                action()
            except Exception as exc:
                result = ("error", exc)
            else:
                result = ("success", None)
            finally:
                close_old_connections()

            with results_lock:
                results.append(result)

        threads = [
            threading.Thread(target=worker, args=(first_action,)),
            threading.Thread(target=worker, args=(second_action,)),
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertFalse(
            any(thread.is_alive() for thread in threads),
            "Concurrency worker did not finish.",
        )
        self.assertEqual(len(results), 2)
        return results

    def test_concurrent_accept_accept_resolves_once(self):
        transition_execution = self._create_pending_acceptance_execution()

        results = self._run_two_actions(
            lambda: WorkflowExecutionService.accept_transition_execution(
                transition_execution=transition_execution,
                user=self.accept_user_one,
            ),
            lambda: WorkflowExecutionService.accept_transition_execution(
                transition_execution=transition_execution,
                user=self.accept_user_two,
            ),
        )

        self.assertEqual(
            sum(result[0] == "success" for result in results),
            1,
        )
        self.assertEqual(
            sum(result[0] == "error" for result in results),
            1,
        )

        transition_execution.refresh_from_db()
        instance = WorkflowInstance.objects.get(pk=transition_execution.instance_id)

        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.ACCEPTED,
        )
        self.assertEqual(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_three,
            ).count(),
            1,
        )
        self.assertEqual(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_one,
            ).count(),
            1,
        )
        self.assertEqual(instance.current_step_id, self.step_three.pk)

    def test_concurrent_accept_reject_allows_only_one_resolution(self):
        transition_execution = self._create_pending_acceptance_execution()

        results = self._run_two_actions(
            lambda: WorkflowExecutionService.accept_transition_execution(
                transition_execution=transition_execution,
                user=self.accept_user_one,
            ),
            lambda: WorkflowExecutionService.reject_transition_execution(
                transition_execution=transition_execution,
                user=self.accept_user_two,
            ),
        )

        self.assertEqual(
            sum(result[0] == "success" for result in results),
            1,
        )
        self.assertEqual(
            sum(result[0] == "error" for result in results),
            1,
        )

        transition_execution.refresh_from_db()
        instance = WorkflowInstance.objects.get(pk=transition_execution.instance_id)

        self.assertIn(
            transition_execution.status,
            (
                WorkflowTransitionExecution.Status.ACCEPTED,
                WorkflowTransitionExecution.Status.REJECTED,
            ),
        )

        destination_count = WorkflowStepExecution.objects.filter(
            instance=instance,
            workflow_step=self.step_three,
        ).count()
        reject_target_count = WorkflowStepExecution.objects.filter(
            instance=instance,
            workflow_step=self.step_one,
        ).count()

        self.assertEqual(
            destination_count,
            1
            if transition_execution.status
            == WorkflowTransitionExecution.Status.ACCEPTED
            else 0,
        )
        self.assertEqual(
            reject_target_count,
            1
            if transition_execution.status
            == WorkflowTransitionExecution.Status.ACCEPTED
            else 2,
        )
        self.assertEqual(
            instance.current_step_id,
            (
                self.step_three.pk
                if transition_execution.status
                == WorkflowTransitionExecution.Status.ACCEPTED
                else self.step_one.pk
            ),
        )

    def test_concurrent_reject_reject_resolves_once(self):
        transition_execution = self._create_pending_acceptance_execution()

        results = self._run_two_actions(
            lambda: WorkflowExecutionService.reject_transition_execution(
                transition_execution=transition_execution,
                user=self.accept_user_one,
            ),
            lambda: WorkflowExecutionService.reject_transition_execution(
                transition_execution=transition_execution,
                user=self.accept_user_two,
            ),
        )

        self.assertEqual(
            sum(result[0] == "success" for result in results),
            1,
        )
        self.assertEqual(
            sum(result[0] == "error" for result in results),
            1,
        )

        transition_execution.refresh_from_db()
        instance = WorkflowInstance.objects.get(pk=transition_execution.instance_id)

        self.assertEqual(
            transition_execution.status,
            WorkflowTransitionExecution.Status.REJECTED,
        )
        self.assertEqual(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_one,
            ).count(),
            2,
        )
        self.assertEqual(
            WorkflowStepExecution.objects.filter(
                instance=instance,
                workflow_step=self.step_three,
            ).count(),
            0,
        )
        self.assertEqual(instance.current_step_id, self.step_one.pk)
