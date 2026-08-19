import os
import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

django.setup()

from django.core.exceptions import ValidationError

from workflow.models import (
    WorkflowInstance,
    WorkflowStepExecution,
    FormData,
)

from workflow.form_services import (
    DynamicFormService,
)


# ============================================================
# CONFIG
# ============================================================

INSTANCE_ID = 27


# ============================================================
# LOAD INSTANCE
# ============================================================

instance = (
    WorkflowInstance.objects
    .select_related(
        "workflow",
        "current_step",
    )
    .get(pk=INSTANCE_ID)
)

executions = list(
    WorkflowStepExecution.objects
    .filter(instance=instance)
    .select_related(
        "workflow_step",
        "performed_by",
    )
    .order_by("performed_at")
)

current_execution = (
    WorkflowStepExecution.objects
    .filter(
        instance=instance,
        workflow_step=instance.current_step,
    )
    .order_by("-performed_at")
    .first()
)

previous_executions = [
    execution
    for execution in executions
    if execution.workflow_step_id != instance.current_step_id
]


print("\n" + "=" * 70)
print("WORKFLOW FORM LOCK CHECK")
print("=" * 70)

print(f"Instance ID       : {instance.pk}")
print(f"Workflow          : {instance.workflow.name}")
print(f"Current Step      : {instance.current_step.name}")
print(f"Status            : {instance.status}")


# ============================================================
# HELPERS
# ============================================================

passed = 0
failed = 0


def check(name, condition):
    global passed, failed

    if condition:
        print(f"✅ PASS  | {name}")
        passed += 1
    else:
        print(f"❌ FAIL  | {name}")
        failed += 1


# ============================================================
# STEP EXECUTIONS
# ============================================================

print("\n" + "-" * 70)
print("STEP EXECUTIONS")
print("-" * 70)

for execution in executions:
    print(
        f"""
ID                : {execution.pk}
Step              : {execution.workflow_step.name}
Submitted         : {execution.is_submitted}
Submitted At      : {execution.submitted_at}
"""
    )


# ============================================================
# BASIC STATE CHECKS
# ============================================================

print("\n" + "=" * 70)
print("AUTOMATED LOCK VALIDATION")
print("=" * 70)

print("\n" + "-" * 70)
print("TEST: CURRENT STEP STATE")
print("-" * 70)

check(
    "Current step execution exists",
    current_execution is not None,
)

if current_execution:
    check(
        "Current step is not submitted",
        current_execution.is_submitted is False,
    )


# ============================================================
# PREVIOUS STEP STATE
# ============================================================

print("\n" + "-" * 70)
print("TEST: PREVIOUS STEP LOCK STATE")
print("-" * 70)

previous_execution = (
    previous_executions[-1]
    if previous_executions
    else None
)

check(
    "Previous step execution exists",
    previous_execution is not None,
)

if previous_execution:
    check(
        "Previous step is submitted",
        previous_execution.is_submitted is True,
    )

    check(
        "Previous step has submitted_at",
        previous_execution.submitted_at is not None,
    )


# ============================================================
# CURRENT STEP SAVE TEST
# ============================================================

print("\n" + "-" * 70)
print("TEST: CURRENT STEP SAVE")
print("-" * 70)

try:
    DynamicFormService.save_form_for_step(
        instance=instance,
        user=instance.current_step.workflow.memberships
        .filter(
            is_active=True,
        )
        .first()
        .user,
        submitted_data={},
    )

    current_save_allowed = True

except ValidationError as exc:
    current_save_allowed = False
    print(
        f"ValidationError: {exc}"
    )

except Exception as exc:
    current_save_allowed = False
    print(
        f"Unexpected error: {type(exc).__name__}: {exc}"
    )


check(
    "Current unsubmitted step allows save",
    current_save_allowed,
)


# ============================================================
# DIRECT SERVICE LOCK TEST
# ============================================================

print("\n" + "-" * 70)
print("TEST: SUBMITTED STEP IS LOCKED")
print("-" * 70)

if previous_execution:

    original_current_step = instance.current_step

    try:
        # Temporarily move the in-memory instance to the
        # previous submitted step.
        instance.current_step = (
            previous_execution.workflow_step
        )

        DynamicFormService.save_form_for_step(
            instance=instance,
            user=previous_execution.performed_by,
            submitted_data={},
        )

        previous_save_allowed = True

    except ValidationError as exc:
        previous_save_allowed = False

        print(
            f"ValidationError: {exc}"
        )

    except Exception as exc:
        previous_save_allowed = False

        print(
            f"Unexpected error: {type(exc).__name__}: {exc}"
        )

    finally:
        instance.current_step = original_current_step

    check(
        "Previous submitted step is locked",
        previous_save_allowed is False,
    )

else:
    print(
        "⚠️ Previous step execution not available."
    )


# ============================================================
# RESULT
# ============================================================

print("\n" + "=" * 70)
print("RESULT")
print("=" * 70)

print(
    f"✅ PASSED : {passed}"
)

print(
    f"❌ FAILED : {failed}"
)

if failed == 0:
    print(
        "\n🎉 ALL FORM LOCK CHECKS PASSED"
    )
else:
    print(
        "\n⚠️ FORM LOCK TEST FAILED"
    )