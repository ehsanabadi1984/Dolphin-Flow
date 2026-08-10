import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model

from workflow.models import (
    Workflow,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowTransition,
)
from workflow.authorization import WorkflowAuthorizationService


User = get_user_model()


TEST_PREFIX = "Allowed Transitions Test"


def reset_test_data():
    WorkflowPermission.objects.filter(
        workflow__name=TEST_PREFIX,
    ).delete()

    WorkflowTransition.objects.filter(
        workflow__name=TEST_PREFIX,
    ).delete()

    WorkflowMembership.objects.filter(
        workflow__name=TEST_PREFIX,
    ).delete()

    WorkflowStep.objects.filter(
        workflow__name=TEST_PREFIX,
    ).delete()

    Workflow.objects.filter(
        name=TEST_PREFIX,
    ).delete()

    User.objects.filter(
        username="allowed_transitions_user",
    ).delete()


def setup_data():
    user = User.objects.create_user(
        username="allowed_transitions_user",
        password="test-password",
    )

    workflow = Workflow.objects.create(
        name=TEST_PREFIX,
        code="ALLOWED_TRANSITIONS_TEST",
        is_active=True,
    )

    WorkflowMembership.objects.create(
        workflow=workflow,
        user=user,
        role=WorkflowMembership.Role.EXECUTOR,
        is_active=True,
    )

    step_one = WorkflowStep.objects.create(
        workflow=workflow,
        name="Test Step One",
        code="STEP_ONE",
        order=1,
        is_active=True,
    )

    step_two = WorkflowStep.objects.create(
        workflow=workflow,
        name="Test Step Two",
        code="STEP_TWO",
        order=2,
        is_active=True,
    )

    step_three = WorkflowStep.objects.create(
        workflow=workflow,
        name="Test Step Three",
        code="STEP_THREE",
        order=3,
        is_active=True,
    )

    transition_allowed = WorkflowTransition.objects.create(
        workflow=workflow,
        from_step=step_one,
        to_step=step_two,
        name="Allowed Transition",
        code="ALLOWED",
        is_active=True,
    )

    transition_denied = WorkflowTransition.objects.create(
        workflow=workflow,
        from_step=step_one,
        to_step=step_three,
        name="Denied Transition",
        code="DENIED",
        is_active=True,
    )

    transition_inactive = WorkflowTransition.objects.create(
        workflow=workflow,
        from_step=step_one,
        to_step=step_three,
        name="Inactive Transition",
        code="INACTIVE",
        is_active=False,
    )

    transition_other_step = WorkflowTransition.objects.create(
        workflow=workflow,
        from_step=step_two,
        to_step=step_three,
        name="Other Step Transition",
        code="OTHER_STEP",
        is_active=True,
    )

    return {
        "user": user,
        "workflow": workflow,
        "step_one": step_one,
        "step_two": step_two,
        "step_three": step_three,
        "allowed": transition_allowed,
        "denied": transition_denied,
        "inactive": transition_inactive,
        "other_step": transition_other_step,
    }


def add_permission(
    *,
    workflow,
    user=None,
    role=None,
    transition=None,
    effect=WorkflowPermission.Effect.ALLOW,
):
    return WorkflowPermission.objects.create(
        workflow=workflow,
        transition=transition,
        user=user,
        role=role,
        action=WorkflowPermission.Action.TRANSITION,
        effect=effect,
    )


def test_role_allow(data):
    print("[TEST] 1. Role ALLOW")

    add_permission(
        workflow=data["workflow"],
        role=WorkflowMembership.Role.EXECUTOR,
        transition=data["allowed"],
        effect=WorkflowPermission.Effect.ALLOW,
    )

    transitions = WorkflowAuthorizationService.get_allowed_transitions(
        user=data["user"],
        workflow=data["workflow"],
        from_step=data["step_one"],
    )

    result = data["allowed"] in transitions

    print(
        f"[{'PASS' if result else 'FAIL'}] "
        f"Role ALLOW -> allowed transition returned: {result}"
    )

    assert result is True


def test_role_deny(data):
    print("[TEST] 2. Role DENY")

    WorkflowPermission.objects.all().delete()

    add_permission(
        workflow=data["workflow"],
        role=WorkflowMembership.Role.EXECUTOR,
        transition=data["denied"],
        effect=WorkflowPermission.Effect.DENY,
    )

    transitions = WorkflowAuthorizationService.get_allowed_transitions(
        user=data["user"],
        workflow=data["workflow"],
        from_step=data["step_one"],
    )

    result = data["denied"] not in transitions

    print(
        f"[{'PASS' if result else 'FAIL'}] "
        f"Role DENY -> denied transition excluded: {result}"
    )

    assert result is True


def test_user_deny_overrides_role_allow(data):
    print("[TEST] 3. User DENY overrides Role ALLOW")

    WorkflowPermission.objects.all().delete()

    add_permission(
        workflow=data["workflow"],
        role=WorkflowMembership.Role.EXECUTOR,
        transition=data["allowed"],
        effect=WorkflowPermission.Effect.ALLOW,
    )

    add_permission(
        workflow=data["workflow"],
        user=data["user"],
        transition=data["allowed"],
        effect=WorkflowPermission.Effect.DENY,
    )

    transitions = WorkflowAuthorizationService.get_allowed_transitions(
        user=data["user"],
        workflow=data["workflow"],
        from_step=data["step_one"],
    )

    result = data["allowed"] not in transitions

    print(
        f"[{'PASS' if result else 'FAIL'}] "
        f"User DENY overrides Role ALLOW: {result}"
    )

    assert result is True


def test_user_allow_overrides_role_deny(data):
    print("[TEST] 4. User ALLOW overrides Role DENY")

    WorkflowPermission.objects.all().delete()

    add_permission(
        workflow=data["workflow"],
        role=WorkflowMembership.Role.EXECUTOR,
        transition=data["allowed"],
        effect=WorkflowPermission.Effect.DENY,
    )

    add_permission(
        workflow=data["workflow"],
        user=data["user"],
        transition=data["allowed"],
        effect=WorkflowPermission.Effect.ALLOW,
    )

    transitions = WorkflowAuthorizationService.get_allowed_transitions(
        user=data["user"],
        workflow=data["workflow"],
        from_step=data["step_one"],
    )

    result = data["allowed"] in transitions

    print(
        f"[{'PASS' if result else 'FAIL'}] "
        f"User ALLOW overrides Role DENY: {result}"
    )

    assert result is True


def test_inactive_and_other_step_excluded(data):
    print("[TEST] 5. Inactive / other-step transitions excluded")

    WorkflowPermission.objects.all().delete()

    add_permission(
        workflow=data["workflow"],
        role=WorkflowMembership.Role.EXECUTOR,
        transition=data["inactive"],
        effect=WorkflowPermission.Effect.ALLOW,
    )

    add_permission(
        workflow=data["workflow"],
        role=WorkflowMembership.Role.EXECUTOR,
        transition=data["other_step"],
        effect=WorkflowPermission.Effect.ALLOW,
    )

    transitions = WorkflowAuthorizationService.get_allowed_transitions(
        user=data["user"],
        workflow=data["workflow"],
        from_step=data["step_one"],
    )

    inactive_excluded = data["inactive"] not in transitions
    other_step_excluded = data["other_step"] not in transitions

    result = inactive_excluded and other_step_excluded

    print(
        f"[{'PASS' if result else 'FAIL'}] "
        f"Inactive excluded: {inactive_excluded}, "
        f"other-step excluded: {other_step_excluded}"
    )

    assert result is True


def test_no_permission(data):
    print("[TEST] 6. No permission")

    WorkflowPermission.objects.all().delete()

    transitions = WorkflowAuthorizationService.get_allowed_transitions(
        user=data["user"],
        workflow=data["workflow"],
        from_step=data["step_one"],
    )

    result = len(transitions) == 0

    print(
        f"[{'PASS' if result else 'FAIL'}] "
        f"No permission -> empty result: {result}"
    )

    assert result is True


def main():
    print("=" * 60)
    print("ALLOWED TRANSITIONS AUTHORIZATION TEST")
    print("=" * 60)

    reset_test_data()

    data = setup_data()

    try:
        test_role_allow(data)
        test_role_deny(data)
        test_user_deny_overrides_role_allow(data)
        test_user_allow_overrides_role_deny(data)
        test_inactive_and_other_step_excluded(data)
        test_no_permission(data)

        print("=" * 60)
        print("ALLOWED TRANSITIONS TEST PASSED")
        print("=" * 60)

    finally:
        reset_test_data()


if __name__ == "__main__":
    main()