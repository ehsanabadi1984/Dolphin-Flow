import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from workflow.models import (
    Workflow,
    WorkflowMembership,
    WorkflowPermission,
)
from workflow.authorization import WorkflowAuthorizationService


User = get_user_model()


def result(name, value, expected):
    status = "PASS" if value == expected else "FAIL"

    print(
        f"[{status}] {name}: "
        f"result={value}, expected={expected}"
    )

    return value == expected


# ---------------------------------------------------------
# Users
# ---------------------------------------------------------

user = User.objects.filter(username="auth_test_user").first()

if not user:
    user = User.objects.create_user(
        username="auth_test_user",
        password="test-password",
    )

user.is_active = True
user.save(update_fields=["is_active"])


# ---------------------------------------------------------
# Workflow
# ---------------------------------------------------------

workflow = (
    Workflow.objects
    .filter(code="AUTH_TEST")
    .first()
)

if not workflow:
    workflow = Workflow.objects.create(
        name="Authorization Test Workflow",
        code="AUTH_TEST",
        is_active=True,
    )


# ---------------------------------------------------------
# Membership
# ---------------------------------------------------------

membership, _ = WorkflowMembership.objects.get_or_create(
    workflow=workflow,
    user=user,
)

membership.is_active = True
membership.role = WorkflowMembership.Role.EXECUTOR
membership.save()


# ---------------------------------------------------------
# Clean previous test permissions
# ---------------------------------------------------------

WorkflowPermission.objects.filter(
    workflow=workflow,
    user=user,
).delete()

WorkflowPermission.objects.filter(
    workflow=workflow,
    role=membership.role,
).delete()


print()
print("=" * 60)
print("AUTHORIZATION SERVICE TEST")
print("=" * 60)


# ---------------------------------------------------------
# TEST 1
# Role ALLOW
# ---------------------------------------------------------

WorkflowPermission.objects.create(
    workflow=workflow,
    role=membership.role,
    action=WorkflowPermission.Action.VIEW,
    effect=WorkflowPermission.Effect.ALLOW,
)

allowed = WorkflowAuthorizationService.has_permission(
    user=user,
    workflow=workflow,
    action=WorkflowPermission.Action.VIEW,
)

result(
    "1. Role ALLOW",
    allowed,
    True,
)


# ---------------------------------------------------------
# TEST 2
# Explicit User DENY overrides Role ALLOW
# ---------------------------------------------------------

WorkflowPermission.objects.create(
    workflow=workflow,
    user=user,
    action=WorkflowPermission.Action.VIEW,
    effect=WorkflowPermission.Effect.DENY,
)

allowed = WorkflowAuthorizationService.has_permission(
    user=user,
    workflow=workflow,
    action=WorkflowPermission.Action.VIEW,
)

result(
    "2. User DENY overrides Role ALLOW",
    allowed,
    False,
)


# ---------------------------------------------------------
# TEST 3
# Explicit User ALLOW overrides Role DENY
# ---------------------------------------------------------

WorkflowPermission.objects.filter(
    workflow=workflow,
    user=user,
).delete()

WorkflowPermission.objects.filter(
    workflow=workflow,
    role=membership.role,
).delete()

WorkflowPermission.objects.create(
    workflow=workflow,
    role=membership.role,
    action=WorkflowPermission.Action.EXECUTE,
    effect=WorkflowPermission.Effect.DENY,
)

WorkflowPermission.objects.create(
    workflow=workflow,
    user=user,
    action=WorkflowPermission.Action.EXECUTE,
    effect=WorkflowPermission.Effect.ALLOW,
)

allowed = WorkflowAuthorizationService.has_permission(
    user=user,
    workflow=workflow,
    action=WorkflowPermission.Action.EXECUTE,
)

result(
    "3. User ALLOW overrides Role DENY",
    allowed,
    True,
)


# ---------------------------------------------------------
# TEST 4
# No permission => DENY
# ---------------------------------------------------------

WorkflowPermission.objects.filter(
    workflow=workflow,
).delete()

allowed = WorkflowAuthorizationService.has_permission(
    user=user,
    workflow=workflow,
    action=WorkflowPermission.Action.MANAGE,
)

result(
    "4. No permission => DENY",
    allowed,
    False,
)


print("=" * 60)
print("AUTHORIZATION TEST FINISHED")
print("=" * 60)
print()