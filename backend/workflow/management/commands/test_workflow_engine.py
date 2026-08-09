import uuid

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

from workflow.models import (
    Workflow,
    WorkflowMembership,
    WorkflowStep,
    WorkflowTransition,
    WorkflowInstance,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
)
from workflow.services import WorkflowExecutionService


class Command(BaseCommand):
    help = "Run an integration test for the Workflow Engine."

    def handle(self, *args, **options):
        self.stdout.write("")
        self.stdout.write("=== Workflow Engine Test ===")
        self.stdout.write("")

        # ---------------------------------------------------------
        # 1. User
        # ---------------------------------------------------------

        User = get_user_model()

        user, _ = User.objects.get_or_create(
            username="workflow_test_user",
            defaults={
                "first_name": "Workflow",
                "last_name": "Tester",
                "email": "workflow-test@example.com",
                "is_active": True,
            },
        )

        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])

        self.stdout.write(
            self.style.SUCCESS(
                f"User: {user.username}"
            )
        )

        # ---------------------------------------------------------
        # 2. Create a completely isolated Workflow
        # ---------------------------------------------------------

        test_id = uuid.uuid4().hex[:8].upper()

        workflow = Workflow.objects.create(
            name=f"Test Workflow {test_id}",
            code=f"TEST_WORKFLOW_{test_id}",
            description="Workflow Engine integration test.",
            is_active=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Workflow: {workflow.name}"
            )
        )

        # ---------------------------------------------------------
        # 3. Membership
        # ---------------------------------------------------------

        membership = WorkflowMembership.objects.create(
            workflow=workflow,
            user=user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Membership: OK"
            )
        )

        # ---------------------------------------------------------
        # 4. Workflow Steps
        # ---------------------------------------------------------

        step_1 = WorkflowStep.objects.create(
            workflow=workflow,
            name="Test Start",
            code="TEST_START",
            description="Initial test step.",
            order=1,
            is_active=True,
        )

        step_2 = WorkflowStep.objects.create(
            workflow=workflow,
            name="Test Finish",
            code="TEST_FINISH",
            description="Final test step.",
            order=2,
            is_active=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Steps: OK"
            )
        )

        # ---------------------------------------------------------
        # 5. Transition
        # ---------------------------------------------------------

        transition = WorkflowTransition.objects.create(
            workflow=workflow,
            from_step=step_1,
            to_step=step_2,
            name="Start to Finish",
            code="TEST_START_TO_FINISH",
            description="Test transition.",
            is_active=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Transition: OK"
            )
        )

        # ---------------------------------------------------------
        # 6. Start Workflow
        # ---------------------------------------------------------

        instance = WorkflowExecutionService.start_workflow(
            workflow=workflow,
            user=user,
            data={
                "test": True,
                "source": "management_command",
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Instance created: #{instance.pk}"
            )
        )

        self.stdout.write(
            f"Current step: {instance.current_step}"
        )

        # ---------------------------------------------------------
        # 7. Validate test setup
        # ---------------------------------------------------------

        if instance.current_step_id != transition.from_step_id:
            raise AssertionError(
                "Test setup error: instance current step "
                "does not match transition source step."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Transition source matches current step: OK"
            )
        )

        # ---------------------------------------------------------
        # 8. Execute Transition
        # ---------------------------------------------------------

        execution = WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=transition,
            user=user,
            notes="Test transition execution",
            data={
                "test": True,
            },
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Transition execution: #{execution.pk}"
            )
        )

        # ---------------------------------------------------------
        # 9. Refresh instance
        # ---------------------------------------------------------

        instance.refresh_from_db()

        self.stdout.write(
            f"New current step: {instance.current_step}"
        )

        self.stdout.write(
            f"Status: {instance.status}"
        )

        # ---------------------------------------------------------
        # 10. Verify execution records
        # ---------------------------------------------------------

        step_execution_count = (
            WorkflowStepExecution.objects
            .filter(instance=instance)
            .count()
        )

        transition_execution_count = (
            WorkflowTransitionExecution.objects
            .filter(instance=instance)
            .count()
        )

        self.stdout.write(
            f"Step executions: {step_execution_count}"
        )

        self.stdout.write(
            f"Transition executions: {transition_execution_count}"
        )

        # ---------------------------------------------------------
        # 11. Assertions
        # ---------------------------------------------------------

        if instance.current_step_id != step_2.id:
            raise AssertionError(
                "Workflow did not move to the destination step."
            )

        if step_execution_count != 2:
            raise AssertionError(
                "Expected exactly 2 step executions."
            )

        if transition_execution_count != 1:
            raise AssertionError(
                "Expected exactly 1 transition execution."
            )

        # ---------------------------------------------------------
        # 12. Final result
        # ---------------------------------------------------------

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "============================================================"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "TEST PASSED"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                "============================================================"
            )
        )
        self.stdout.write("")