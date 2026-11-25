from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from workflow.models import (
    Notification,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
    WorkflowTransitionExecution,
)
from workflow.services import WorkflowExecutionService
from workflow.acceptance_queue_services import PendingAcceptanceQueueService


User = get_user_model()


class PendingAcceptanceQueueServiceTests(TestCase):

    def setUp(self):
        self.sender = User.objects.create_user(
            username="pending_queue_sender",
            password="test-password",
        )
        self.receiver = User.objects.create_user(
            username="pending_queue_receiver",
            password="test-password",
        )

        self.workflow = Workflow.objects.create(
            name="Pending Queue Workflow",
            code="PENDING_QUEUE_WORKFLOW",
            is_active=True,
        )

        self.step_one = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step One",
            code="PENDING_QUEUE_STEP_ONE",
            order=1,
            is_active=True,
            assigned_to=self.sender,
        )
        self.step_two = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step Two",
            code="PENDING_QUEUE_STEP_TWO",
            order=2,
            is_active=True,
            assigned_to=self.sender,
        )
        self.step_three = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Step Three",
            code="PENDING_QUEUE_STEP_THREE",
            order=3,
            is_active=True,
            assigned_to=self.sender,
        )

        self.transition_one = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Step One to Two",
            code="PENDING_QUEUE_TRANSITION_ONE",
            from_step=self.step_one,
            to_step=self.step_two,
            is_active=True,
        )
        self.transition_two = WorkflowTransition.objects.create(
            workflow=self.workflow,
            name="Step Two to Three",
            code="PENDING_QUEUE_TRANSITION_TWO",
            from_step=self.step_two,
            to_step=self.step_three,
            is_active=True,
            requires_acceptance=True,
            reject_to_step=self.step_one,
        )

        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.sender,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.receiver,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        WorkflowPermission.objects.create(
            workflow=self.workflow,
            user=self.sender,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        for step in (self.step_one, self.step_two, self.step_three):
            WorkflowPermission.objects.create(
                workflow=self.workflow,
                step=step,
                user=self.sender,
                action=WorkflowPermission.Action.EXECUTE,
                effect=WorkflowPermission.Effect.ALLOW,
            )


        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.transition_one,
            user=self.sender,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            transition=self.transition_two,
            user=self.sender,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )

    def grant_step_action(self, *, user, step, action_code, effect="ALLOW"):
        return WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=step,
            user=user,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code=action_code,
            effect=effect,
        )

    def grant_role_step_action(self, *, role, step, action_code, effect="ALLOW"):
        return WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=step,
            role=role,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code=action_code,
            effect=effect,
        )

    def create_pending(self):
        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.sender,
        )
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_one,
            user=self.sender,
        )
        return WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=self.transition_two,
            user=self.sender,
        )

    def test_start_notifies_the_resolved_initial_execution_assignee(self):
        self.step_one.assigned_to = self.receiver
        self.step_one.save(update_fields=["assigned_to"])
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_one,
            user=self.receiver,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.sender,
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=self.receiver,
                notification_type=Notification.NotificationType.ACTION_REQUIRED,
                workflow_instance=instance,
                workflow_step=self.step_one,
            ).exists()
        )

    def test_accept_notifies_destination_assignee_separately_from_outcome_recipient(self):
        pending = self.create_pending()
        destination_assignee = User.objects.create_user(
            username="pending_accept_destination_assignee",
            password="test-password",
        )
        self.step_three.assigned_to = destination_assignee
        self.step_three.save(update_fields=["assigned_to"])
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=destination_assignee,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_three,
            user=destination_assignee,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
        )

        WorkflowExecutionService.accept_transition_execution(
            transition_execution=pending,
            user=self.receiver,
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=destination_assignee,
                notification_type=Notification.NotificationType.ACTION_REQUIRED,
                workflow_step=self.step_three,
                workflow_instance=pending.instance,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.sender,
                notification_type=Notification.NotificationType.TRANSITION_EXECUTED,
                transition_execution=pending,
            ).exists()
        )

    def test_reject_notifies_return_step_assignee_separately_from_outcome_recipient(self):
        pending = self.create_pending()
        return_assignee = User.objects.create_user(
            username="pending_reject_return_assignee",
            password="test-password",
        )
        self.step_one.assigned_to = return_assignee
        self.step_one.save(update_fields=["assigned_to"])
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=return_assignee,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )
        WorkflowPermission.objects.create(
            workflow=self.workflow,
            step=self.step_one,
            user=return_assignee,
            action=WorkflowPermission.Action.EXECUTE,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="REJECT",
        )

        WorkflowExecutionService.reject_transition_execution(
            transition_execution=pending,
            user=self.receiver,
        )

        self.assertTrue(
            Notification.objects.filter(
                recipient=return_assignee,
                notification_type=Notification.NotificationType.ACTION_REQUIRED,
                workflow_step=self.step_one,
                workflow_instance=pending.instance,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.sender,
                notification_type=Notification.NotificationType.TRANSITION_EXECUTED,
                transition_execution=pending,
            ).exists()
        )

    def test_websocket_publish_failure_does_not_fail_notification_creation(self):
        from unittest.mock import patch
        from workflow.notification_services import NotificationService

        with patch(
            "workflow.notification_services._schedule_sms_safely"
        ), patch(
            "workflow.notification_services.async_to_sync",
            side_effect=RuntimeError("websocket unavailable"),
        ):
            with self.captureOnCommitCallbacks(execute=True):
                notification = NotificationService.create(
                    recipient=self.receiver,
                    notification_type=Notification.NotificationType.WORKFLOW_STARTED,
                    title="شروع فرآیند",
                    message="فرآیند آغاز شد",
                )

        self.assertTrue(
            Notification.objects.filter(pk=notification.pk).exists()
        )

    def test_returns_pending_acceptance_execution_with_accept_permission(self):
        execution = self.create_pending()
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
        )

        result = list(
            PendingAcceptanceQueueService(self.receiver).get_queryset()
        )

        self.assertEqual([item.pk for item in result], [execution.pk])
        self.assertEqual(result[0].performed_by_id, self.sender.pk)
        self.assertEqual(result[0].transition_id, self.transition_two.pk)

    def test_returns_pending_execution_with_reject_permission_only(self):
        execution = self.create_pending()
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="REJECT",
        )

        result = list(
            PendingAcceptanceQueueService(self.receiver).get_queryset()
        )

        self.assertEqual([item.pk for item in result], [execution.pk])

    def test_requires_at_least_one_effective_accept_or_reject_permission(self):
        self.create_pending()

        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .exists()
        )

    def test_user_deny_overrides_user_allow(self):
        self.create_pending()
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
            effect="ALLOW",
        )
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
            effect="DENY",
        )

        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .exists()
        )

    def test_user_allow_overrides_role_deny(self):
        execution = self.create_pending()
        self.grant_role_step_action(
            role=WorkflowMembership.Role.EXECUTOR,
            step=self.step_three,
            action_code="ACCEPT",
            effect="DENY",
        )
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
            effect="ALLOW",
        )

        result = list(
            PendingAcceptanceQueueService(self.receiver).get_queryset()
        )

        self.assertEqual([item.pk for item in result], [execution.pk])

    def test_role_deny_blocks_role_allow(self):
        self.create_pending()
        self.grant_role_step_action(
            role=WorkflowMembership.Role.EXECUTOR,
            step=self.step_three,
            action_code="ACCEPT",
            effect="ALLOW",
        )
        self.grant_role_step_action(
            role=WorkflowMembership.Role.EXECUTOR,
            step=self.step_three,
            action_code="ACCEPT",
            effect="DENY",
        )

        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .exists()
        )

    def test_inactive_membership_excludes_queue(self):
        self.create_pending()
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
        )
        membership = WorkflowMembership.objects.get(
            workflow=self.workflow,
            user=self.receiver,
        )
        membership.is_active = False
        membership.save(update_fields=["is_active"])

        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .exists()
        )

    def test_inactive_workflow_transition_target_or_instance_is_excluded(self):
        execution = self.create_pending()
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
        )

        self.workflow.is_active = False
        self.workflow.save(update_fields=["is_active"])
        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=execution.pk)
            .exists()
        )

        self.workflow.is_active = True
        self.workflow.save(update_fields=["is_active"])
        self.transition_two.is_active = False
        self.transition_two.save(update_fields=["is_active"])
        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=execution.pk)
            .exists()
        )

        self.transition_two.is_active = True
        self.transition_two.save(update_fields=["is_active"])
        self.step_three.is_active = False
        self.step_three.save(update_fields=["is_active"])
        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=execution.pk)
            .exists()
        )

        self.step_three.is_active = True
        self.step_three.save(update_fields=["is_active"])
        instance = WorkflowInstance.objects.get(pk=execution.instance_id)
        instance.status = WorkflowInstance.Status.COMPLETED
        instance.save(update_fields=["status"])
        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=execution.pk)
            .exists()
        )

    def test_superseded_acceptance_is_excluded_from_pending_queue(self):
        execution = self.create_pending()
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
        )
        execution.status = WorkflowTransitionExecution.Status.SUPERSEDED
        execution.resolved_at = timezone.now()
        execution.save(update_fields=["status", "resolved_at"])

        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=execution.pk)
            .exists()
        )

    def test_non_acceptance_transition_is_excluded(self):
        instance = WorkflowExecutionService.start_workflow(
            workflow=self.workflow,
            user=self.sender,
        )
        execution = WorkflowTransitionExecution.objects.create(
            instance=instance,
            transition=self.transition_one,
            performed_by=self.sender,
            status=WorkflowTransitionExecution.Status.PENDING,
        )
        self.grant_step_action(
            user=self.receiver,
            step=self.step_two,
            action_code="ACCEPT",
        )

        self.assertFalse(
            PendingAcceptanceQueueService(self.receiver)
            .get_queryset()
            .filter(pk=execution.pk)
            .exists()
        )

    def test_queryset_is_chainable_and_oldest_first(self):
        first = self.create_pending()
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
        )
        first.performed_at = first.performed_at.replace(year=2020)
        first.save(update_fields=["performed_at"])

        second = self.create_pending()
        second.performed_at = second.performed_at.replace(year=2021)
        second.save(update_fields=["performed_at"])

        result = PendingAcceptanceQueueService(self.receiver).get_queryset()
        self.assertEqual(result.count(), 2)
        self.assertEqual(list(result.values_list("pk", flat=True)), [first.pk, second.pk])
        self.assertEqual(result.filter(pk=second.pk).count(), 1)

    def test_multiple_workflows_are_supported(self):
        first = self.create_pending()
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
        )

        workflow_two = Workflow.objects.create(
            name="Pending Queue Workflow Two",
            code="PENDING_QUEUE_WORKFLOW_TWO",
            is_active=True,
        )
        step_a = WorkflowStep.objects.create(
            workflow=workflow_two,
            name="Step A",
            code="PENDING_QUEUE_STEP_A",
            order=1,
            assigned_to=self.sender,
        )
        step_b = WorkflowStep.objects.create(
            workflow=workflow_two,
            name="Step B",
            code="PENDING_QUEUE_STEP_B",
            order=2,
            assigned_to=self.sender,
        )
        transition = WorkflowTransition.objects.create(
            workflow=workflow_two,
            name="A to B",
            code="PENDING_QUEUE_TRANSITION_TWO",
            from_step=step_a,
            to_step=step_b,
            requires_acceptance=True,
        )
        WorkflowMembership.objects.create(
            workflow=workflow_two,
            user=self.sender,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        WorkflowMembership.objects.create(
            workflow=workflow_two,
            user=self.receiver,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        WorkflowPermission.objects.create(
            workflow=workflow_two,
            user=self.sender,
            action=WorkflowPermission.Action.START,
            effect=WorkflowPermission.Effect.ALLOW,
        )

        for step in (step_a, step_b):
            WorkflowPermission.objects.create(
                workflow=workflow_two,
                step=step,
                user=self.sender,
                action=WorkflowPermission.Action.EXECUTE,
                effect=WorkflowPermission.Effect.ALLOW,
            )

        WorkflowPermission.objects.create(
            workflow=workflow_two,
            transition=transition,
            user=self.sender,
            action=WorkflowPermission.Action.TRANSITION,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        self.grant_step_action(
            user=self.receiver,
            step=self.step_three,
            action_code="ACCEPT",
        )
        WorkflowPermission.objects.create(
            workflow=workflow_two,
            step=step_b,
            user=self.receiver,
            action=WorkflowPermission.Action.STEP_ACTION,
            action_code="ACCEPT",
            effect=WorkflowPermission.Effect.ALLOW,
        )

        instance_two = WorkflowExecutionService.start_workflow(
            workflow=workflow_two,
            user=self.sender,
        )
        execution_two = WorkflowTransitionExecution.objects.create(
            instance=instance_two,
            transition=transition,
            performed_by=self.sender,
            status=WorkflowTransitionExecution.Status.PENDING,
        )

        result = PendingAcceptanceQueueService(self.receiver).get_queryset()
        self.assertEqual(
            list(result.values_list("pk", flat=True)),
            [first.pk, execution_two.pk],
        )
