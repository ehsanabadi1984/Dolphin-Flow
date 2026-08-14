import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()

from django.core.exceptions import PermissionDenied

from accounts.models import User

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


TEST_WORKFLOW_CODE = "AUTH_ROLE_EXEC_TEST"
TEST_USERNAME = "auth_role_exec_user"


def reset_test_data():
    WorkflowTransitionExecution.objects.filter(
        instance__workflow__code=TEST_WORKFLOW_CODE
    ).delete()

    WorkflowStepExecution.objects.filter(
        instance__workflow__code=TEST_WORKFLOW_CODE
    ).delete()

    WorkflowInstance.objects.filter(
        workflow__code=TEST_WORKFLOW_CODE
    ).delete()

    WorkflowPermission.objects.filter(
        workflow__code=TEST_WORKFLOW_CODE
    ).delete()

    WorkflowTransition.objects.filter(
        workflow__code=TEST_WORKFLOW_CODE
    ).delete()

    WorkflowStep.objects.filter(
        workflow__code=TEST_WORKFLOW_CODE
    ).delete()

    WorkflowMembership.objects.filter(
        workflow__code=TEST_WORKFLOW_CODE
    ).delete()

    Workflow.objects.filter(
        code=TEST_WORKFLOW_CODE
    ).delete()

    User.objects.filter(
        username=TEST_USERNAME
    ).delete()


def setup_test_environment():
    user = User.objects.create_user(
        username=TEST_USERNAME,
        password="test-password",
        is_active=True,
    )

    workflow = Workflow.objects.create(
        name="Authorization Role Execution Test",
        code=TEST_WORKFLOW_CODE,
        is_active=True,
    )

    step_one = WorkflowStep.objects.create(
        workflow=workflow,
        name="Test Step One",
        code="ROLE_STEP_ONE",
        order=1,
        is_active=True,
    )

    step_two = WorkflowStep.objects.create(
        workflow=workflow,
        name="Test Step Two",
        code="ROLE_STEP_TWO",
        order=2,
        is_active=True,
    )

    transition = WorkflowTransition.objects.create(
        workflow=workflow,
        name="Test Transition",
        code="ROLE_TRANSITION",
        from_step=step_one,
        to_step=step_two,
        is_active=True,
    )

    membership = WorkflowMembership.objects.create(
        workflow=workflow,
        user=user,
        role=WorkflowMembership.Role.EXECUTOR,
        is_active=True,
    )

    return (
        user,
        workflow,
        step_one,
        step_two,
        transition,
        membership,
    )


def start_instance(user, workflow):
    return WorkflowExecutionService.start_workflow(
        workflow=workflow,
        user=user,
    )


def test_role_allow():
    print("[TEST] 1. Role ALLOW")

    user, workflow, _, _, transition, _ = setup_test_environment()

    WorkflowPermission.objects.create(
        workflow=workflow,
        role=WorkflowMembership.Role.EXECUTOR,
        action=WorkflowPermission.Action.EXECUTE,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        role=WorkflowMembership.Role.EXECUTOR,
        transition=transition,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    instance = start_instance(user, workflow)

    WorkflowExecutionService.execute_transition(
        instance=instance,
        transition=transition,
        user=user,
    )

    print("[PASS] Role ALLOW -> transition executed")


def test_user_deny_overrides_role_allow():
    print("[TEST] 2. User DENY overrides Role ALLOW")

    reset_test_data()

    user, workflow, _, _, transition, _ = setup_test_environment()

    WorkflowPermission.objects.create(
        workflow=workflow,
        role=WorkflowMembership.Role.EXECUTOR,
        action=WorkflowPermission.Action.EXECUTE,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        role=WorkflowMembership.Role.EXECUTOR,
        transition=transition,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        transition=transition,
        user=user,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.DENY,
    )

    instance = start_instance(user, workflow)

    try:
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=transition,
            user=user,
        )
    except PermissionDenied:
        print(
            "[PASS] User DENY overrides Role ALLOW "
            "-> transition blocked"
        )
        return

    raise AssertionError(
        "Transition should have been denied"
    )


def test_user_allow_overrides_role_deny():
    print("[TEST] 3. User ALLOW overrides Role DENY")

    reset_test_data()

    user, workflow, _, _, transition, _ = setup_test_environment()

    WorkflowPermission.objects.create(
        workflow=workflow,
        role=WorkflowMembership.Role.EXECUTOR,
        action=WorkflowPermission.Action.EXECUTE,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        role=WorkflowMembership.Role.EXECUTOR,
        transition=transition,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.DENY,
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        transition=transition,
        user=user,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    instance = start_instance(user, workflow)

    WorkflowExecutionService.execute_transition(
        instance=instance,
        transition=transition,
        user=user,
    )

    print(
        "[PASS] User ALLOW overrides Role DENY "
        "-> transition executed"
    )


def test_no_permission():
    print("[TEST] 4. No permission")

    reset_test_data()

    user, workflow, _, _, transition, _ = setup_test_environment()

    WorkflowPermission.objects.create(
        workflow=workflow,
        role=WorkflowMembership.Role.EXECUTOR,
        action=WorkflowPermission.Action.EXECUTE,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    instance = start_instance(user, workflow)

    try:
        WorkflowExecutionService.execute_transition(
            instance=instance,
            transition=transition,
            user=user,
        )
    except PermissionDenied:
        print(
            "[PASS] No transition permission "
            "-> transition blocked"
        )
        return

    raise AssertionError(
        "Transition should have been denied"
    )


def main():
    print("=" * 60)
    print("WORKFLOW ROLE/USER EXECUTION AUTHORIZATION TEST")
    print("=" * 60)

    try:
        reset_test_data()

        test_role_allow()
        test_user_deny_overrides_role_allow()
        test_user_allow_overrides_role_deny()
        test_no_permission()

        print("=" * 60)
        print("ROLE/USER EXECUTION AUTHORIZATION TEST PASSED")
        print("=" * 60)

    finally:
        reset_test_data()


if __name__ == "__main__":
    main()
