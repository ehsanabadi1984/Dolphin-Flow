import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from workflow.models import (
    Workflow,
    WorkflowStep,
    WorkflowTransition,
    WorkflowInstance,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
    WorkflowMembership,
    WorkflowPermission,
)
from workflow.services import WorkflowExecutionService


User = get_user_model()


def reset_test_data():
    WorkflowTransitionExecution.objects.filter(
        instance__workflow__code="AUTH_EXEC_TEST"
    ).delete()

    WorkflowStepExecution.objects.filter(
        instance__workflow__code="AUTH_EXEC_TEST"
    ).delete()

    WorkflowInstance.objects.filter(
        workflow__code="AUTH_EXEC_TEST"
    ).delete()

    WorkflowPermission.objects.filter(
        workflow__code="AUTH_EXEC_TEST"
    ).delete()

    WorkflowTransition.objects.filter(
        workflow__code="AUTH_EXEC_TEST"
    ).delete()

    WorkflowStep.objects.filter(
        workflow__code="AUTH_EXEC_TEST"
    ).delete()

    WorkflowMembership.objects.filter(
        workflow__code="AUTH_EXEC_TEST"
    ).delete()

    Workflow.objects.filter(
        code="AUTH_EXEC_TEST"
    ).delete()

    User.objects.filter(
        username="auth_exec_user"
    ).delete()


def create_test_environment():
    user = User.objects.create_user(
        username="auth_exec_user",
        password="test-password",
    )

    workflow = Workflow.objects.create(
        name="Authorization Execution Test",
        code="AUTH_EXEC_TEST",
        is_active=True,
    )

    step_one = WorkflowStep.objects.create(
        workflow=workflow,
        name="Test Step One",
        code="AUTH_EXEC_STEP_ONE",
        order=1,
        is_active=True,
    )

    step_two = WorkflowStep.objects.create(
        workflow=workflow,
        name="Test Step Two",
        code="AUTH_EXEC_STEP_TWO",
        order=2,
        is_active=True,
    )

    transition = WorkflowTransition.objects.create(
        workflow=workflow,
        name="Test Transition",
        code="AUTH_EXEC_TRANSITION",
        from_step=step_one,
        to_step=step_two,
        is_active=True,
    )

    WorkflowMembership.objects.create(
        workflow=workflow,
        user=user,
        role=WorkflowMembership.Role.EXECUTOR,
        is_active=True,
    )

    return user, workflow, step_one, step_two, transition


def test_allow():
    user, workflow, step_one, step_two, transition = (
        create_test_environment()
    )

    # Permission required to start the workflow
    WorkflowPermission.objects.create(
        workflow=workflow,
        user=user,
        action=WorkflowPermission.Action.EXECUTE,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    # Permission required to execute the transition
    WorkflowPermission.objects.create(
        workflow=workflow,
        transition=transition,
        user=user,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    instance = WorkflowExecutionService.start_workflow(
        workflow=workflow,
        user=user,
    )

    WorkflowExecutionService.execute_transition(
        instance=instance,
        transition=transition,
        user=user,
    )

    instance.refresh_from_db()

    assert instance.current_step_id == step_two.pk
    assert (
        instance.status
        == WorkflowInstance.Status.COMPLETED
    )


def test_deny():
    user, workflow, step_one, step_two, transition = (
        create_test_environment()
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        user=user,
        action=WorkflowPermission.Action.EXECUTE,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    WorkflowPermission.objects.create(
    workflow=workflow,
    transition=transition,
    user=user,
    action=WorkflowPermission.Action.TRANSITION,
    effect=WorkflowPermission.Effect.DENY,
    )


    instance = WorkflowExecutionService.start_workflow(
        workflow=workflow,
        user=user,
    )

    try:
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=transition,
            user=user,
        )

    except PermissionDenied:
        instance.refresh_from_db()

        assert instance.current_step_id == step_one.pk

    else:
        raise AssertionError(
            "Transition باید توسط Authorization مسدود می‌شد."
        )


def test_no_permission():
    user, workflow, step_one, step_two, transition = (
        create_test_environment()
    )

    WorkflowPermission.objects.create(
    workflow=workflow,
    user=user,
    action=WorkflowPermission.Action.EXECUTE,
    effect=WorkflowPermission.Effect.ALLOW,
    )
    instance = WorkflowExecutionService.start_workflow(
        workflow=workflow,
        user=user,
    )

    try:
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=transition,
            user=user,
        )

    except PermissionDenied:
        instance.refresh_from_db()

        assert instance.current_step_id == step_one.pk

    else:
        raise AssertionError(
            "کاربر بدون Permission نباید بتواند Transition را اجرا کند."
        )


def main():
    print()
    print("=" * 60)
    print("WORKFLOW EXECUTION AUTHORIZATION TEST")
    print("=" * 60)

    reset_test_data()

    try:
        print("[TEST] 1. Explicit ALLOW")

        reset_test_data()
        test_allow()

        print("[PASS] Explicit ALLOW -> transition executed")

        print("[TEST] 2. Explicit DENY")

        reset_test_data()
        test_deny()

        print("[PASS] Explicit DENY -> transition blocked")

        print("[TEST] 3. No permission")

        reset_test_data()
        test_no_permission()

        print("[PASS] No permission -> transition blocked")

    finally:
        reset_test_data()

    print("=" * 60)
    print("EXECUTION AUTHORIZATION TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()