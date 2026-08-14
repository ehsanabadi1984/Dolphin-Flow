import os
import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

django.setup()

from django.contrib.auth import get_user_model
from django.test import Client

from workflow.models import (
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransition,
    WorkflowTransitionExecution,
)

User = get_user_model()

TEST_WORKFLOW = "Operator Panel Authorization Test"
USERNAME = "operator_panel_auth_user"


def reset_test_data():
    WorkflowTransitionExecution.objects.filter(
        instance__workflow__name=TEST_WORKFLOW,
    ).delete()

    WorkflowStepExecution.objects.filter(
        instance__workflow__name=TEST_WORKFLOW,
    ).delete()

    WorkflowInstance.objects.filter(
        workflow__name=TEST_WORKFLOW,
    ).delete()

    WorkflowPermission.objects.filter(
        workflow__name=TEST_WORKFLOW,
    ).delete()

    WorkflowTransition.objects.filter(
        workflow__name=TEST_WORKFLOW,
    ).delete()

    WorkflowMembership.objects.filter(
        workflow__name=TEST_WORKFLOW,
    ).delete()

    WorkflowStep.objects.filter(
        workflow__name=TEST_WORKFLOW,
    ).delete()

    Workflow.objects.filter(
        name=TEST_WORKFLOW,
    ).delete()

    User.objects.filter(
        username=USERNAME,
    ).delete()

def setup_data():
    user = User.objects.create_user(
        username=USERNAME,
        password="test-password",
    )

    workflow = Workflow.objects.create(
        name=TEST_WORKFLOW,
        code="OPERATOR_PANEL_AUTH_TEST",
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
        name="Step One",
        code="STEP_ONE",
        order=1,
        is_active=True,
    )

    step_two = WorkflowStep.objects.create(
        workflow=workflow,
        name="Step Two",
        code="STEP_TWO",
        order=2,
        is_active=True,
    )

    step_three = WorkflowStep.objects.create(
        workflow=workflow,
        name="Step Three",
        code="STEP_THREE",
        order=3,
        is_active=True,
    )

    allowed_transition = WorkflowTransition.objects.create(
        workflow=workflow,
        from_step=step_one,
        to_step=step_two,
        name="Allowed Transition",
        code="ALLOWED",
        is_active=True,
    )

    denied_transition = WorkflowTransition.objects.create(
        workflow=workflow,
        from_step=step_one,
        to_step=step_three,
        name="Denied Transition",
        code="DENIED",
        is_active=True,
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        transition=allowed_transition,
        role=WorkflowMembership.Role.EXECUTOR,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        transition=denied_transition,
        role=WorkflowMembership.Role.EXECUTOR,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.DENY,
    )

    WorkflowPermission.objects.create(
        workflow=workflow,
        step=step_one,
        role=WorkflowMembership.Role.EXECUTOR,
        action=WorkflowPermission.Action.VIEW,
        effect=WorkflowPermission.Effect.ALLOW,
    )

    return {
        "user": user,
        "workflow": workflow,
        "step_one": step_one,
        "allowed": allowed_transition,
        "denied": denied_transition,
    }


def test_panel_shows_only_allowed_transition(data):
    print("[TEST] 1. Panel shows only allowed transition")

    client = Client(
    enforce_csrf_checks=False,
    )

    client.force_login(data["user"])

    # Create a WorkflowInstance manually.
    from workflow.models import WorkflowInstance

    instance = WorkflowInstance.objects.create(
        workflow=data["workflow"],
        current_step=data["step_one"],
        started_by=data["user"],
        status=WorkflowInstance.Status.ACTIVE,
    )

    response = client.get(
    f"/operator/workflow-instance/{instance.pk}/",
    HTTP_HOST="localhost",
    )

    assert response.status_code == 200

    content = response.content.decode()

    allowed_visible = (
        data["allowed"].name in content
    )

    denied_visible = (
        data["denied"].name in content
    )

    print(
        f"[{'PASS' if allowed_visible else 'FAIL'}] "
        f"Allowed transition visible: {allowed_visible}"
    )

    print(
        f"[{'PASS' if not denied_visible else 'FAIL'}] "
        f"Denied transition hidden: {not denied_visible}"
    )

    assert allowed_visible is True
    assert denied_visible is False

    return instance


def test_direct_post_is_blocked(data, instance):
    print("[TEST] 2. Direct POST to denied transition")

    client = Client()
    client.force_login(data["user"])

    denied_transition = data["denied"]

    response = client.post(
        f"/operator/workflow-instance/"
        f"{instance.pk}/transition/"
        f"{denied_transition.pk}/execute/",
        HTTP_HOST="localhost",
    )

    print(
        f"[PASS] Direct POST returned status={response.status_code}"
    )

    assert response.status_code in (403, 404)

def main():
    print("=" * 60)
    print("OPERATOR PANEL AUTHORIZATION TEST")
    print("=" * 60)

    reset_test_data()

    try:
        data = setup_data()

        instance = test_panel_shows_only_allowed_transition(
            data
        )

        test_direct_post_is_blocked(
            data,
            instance,
        )

        print("=" * 60)
        print("OPERATOR PANEL AUTHORIZATION TEST PASSED")
        print("=" * 60)

    finally:
        reset_test_data()


if __name__ == "__main__":
    main()