import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.utils import timezone

from workflow.models import (
    WorkflowInstance,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
    FormData,
)
from workflow.services import (
    WorkflowExecutionService,
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

print("\n" + "=" * 70)
print("WORKFLOW TRANSITION STATE CHECK")
print("=" * 70)

print(f"Instance ID       : {instance.pk}")
print(f"Workflow          : {instance.workflow.name}")
print(f"Current Step      : {instance.current_step.name}")
print(f"Status            : {instance.status}")

print("\n" + "-" * 70)
print("STEP EXECUTIONS")
print("-" * 70)

executions = (
    WorkflowStepExecution.objects
    .filter(instance=instance)
    .select_related("workflow_step", "performed_by")
    .order_by("performed_at")
)

for execution in executions:
    print(
        f"""
ID                : {execution.pk}
Step              : {execution.workflow_step.name}
Performed By      : {execution.performed_by}
Performed At      : {execution.performed_at}
Submitted         : {execution.is_submitted}
Submitted At      : {execution.submitted_at}
SLA Started       : {execution.sla_started_at}
SLA Due           : {execution.sla_due_at}
SLA Completed     : {execution.sla_completed_at}
SLA Breached      : {execution.sla_breached_at}
"""
    )


# ============================================================
# CURRENT STEP EXECUTION
# ============================================================

current_execution = (
    executions
    .filter(
        workflow_step=instance.current_step,
    )
    .order_by("-performed_at")
    .first()
)

print("-" * 70)
print("CURRENT STEP EXECUTION")
print("-" * 70)

if current_execution:
    print(f"Execution ID      : {current_execution.pk}")
    print(f"Step              : {current_execution.workflow_step.name}")
    print(f"Submitted         : {current_execution.is_submitted}")
    print(f"Submitted At      : {current_execution.submitted_at}")
    print(f"SLA Started       : {current_execution.sla_started_at}")
    print(f"SLA Completed     : {current_execution.sla_completed_at}")
else:
    print("❌ CURRENT STEP EXECUTION NOT FOUND")


# ============================================================
# TRANSITION EXECUTIONS
# ============================================================

print("\n" + "-" * 70)
print("TRANSITION EXECUTIONS")
print("-" * 70)

transition_executions = (
    WorkflowTransitionExecution.objects
    .filter(instance=instance)
    .select_related(
        "transition",
        "transition__from_step",
        "transition__to_step",
        "performed_by",
    )
    .order_by("performed_at")
)

for execution in transition_executions:
    print(
        f"""
ID                : {execution.pk}
Transition        : {execution.transition.name}
From              : {execution.transition.from_step.name}
To                : {execution.transition.to_step.name}
Performed By      : {execution.performed_by}
Performed At      : {execution.performed_at}
Notes             : {execution.notes}
"""
    )


# ============================================================
# FORM DATA
# ============================================================

print("-" * 70)
print("FORM DATA")
print("-" * 70)

form_data = (
    FormData.objects
    .filter(instance=instance)
    .first()
)

if form_data:
    print(f"FormData ID       : {form_data.pk}")
    print(f"Is Submitted      : {form_data.is_submitted}")
    print(f"Submitted At      : {form_data.submitted_at}")
    print(f"Submitted By      : {form_data.submitted_by}")
    print(f"Has Data          : {bool(form_data.data)}")
    print(f"Data Keys         : {list(form_data.data.keys())}")
else:
    print("❌ FORM DATA NOT FOUND")


# ============================================================
# VALIDATION
# ============================================================

print("\n" + "=" * 70)
print("AUTOMATED VALIDATION")
print("=" * 70)

checks = []


# ------------------------------------------------------------
# 1. Instance has current step
# ------------------------------------------------------------

checks.append(
    (
        "Instance has current step",
        instance.current_step_id is not None,
    )
)


# ------------------------------------------------------------
# 2. Current step execution exists
# ------------------------------------------------------------

checks.append(
    (
        "Current step execution exists",
        current_execution is not None,
    )
)


# ------------------------------------------------------------
# 3. Current execution is NOT submitted
#
# A newly entered step must not already be submitted.
# ------------------------------------------------------------

if current_execution:
    checks.append(
        (
            "Current step is not submitted",
            current_execution.is_submitted is False,
        )
    )


# ------------------------------------------------------------
# 4. FormData exists
# ------------------------------------------------------------

checks.append(
    (
        "FormData exists",
        form_data is not None,
    )
)


# ------------------------------------------------------------
# 5. FormData contains data
#
# FormData is shared by the WorkflowInstance and is NOT
# the source of truth for step submission.
# ------------------------------------------------------------

if form_data:
    checks.append(
        (
            "FormData contains data",
            bool(form_data.data),
        )
    )


# ------------------------------------------------------------
# 6. Previous step execution
# ------------------------------------------------------------

previous_execution = None

if current_execution:
    previous_execution = (
        executions
        .filter(
            performed_at__lt=current_execution.performed_at,
        )
        .order_by("-performed_at")
        .first()
    )

checks.append(
    (
        "Previous step execution exists",
        previous_execution is not None,
    )
)


# ------------------------------------------------------------
# 7. Previous step was submitted
#
# THIS is the real source of truth.
# ------------------------------------------------------------

if previous_execution:
    checks.append(
        (
            "Previous step is submitted",
            previous_execution.is_submitted is True,
        )
    )


# ------------------------------------------------------------
# 8. Previous step has submitted_at
# ------------------------------------------------------------

if previous_execution:
    checks.append(
        (
            "Previous step has submitted_at",
            previous_execution.submitted_at is not None,
        )
    )


# ------------------------------------------------------------
# 9. Previous step SLA
#
# SLA is optional.
#
# If SLA was started, it must have been completed.
# If SLA was never started, it means no SLA was configured
# for that execution and this check is considered PASS.
# ------------------------------------------------------------

if previous_execution:

    if previous_execution.sla_started_at is not None:
        checks.append(
            (
                "Previous step SLA completed",
                previous_execution.sla_completed_at is not None,
            )
        )
    else:
        checks.append(
            (
                "Previous step SLA configured",
                True,
            )
        )


# ------------------------------------------------------------
# 10. Transition execution exists
# ------------------------------------------------------------

transition_exists = (
    WorkflowTransitionExecution.objects
    .filter(instance=instance)
    .exists()
)

checks.append(
    (
        "At least one transition execution exists",
        transition_exists,
    )
)


# ============================================================
# PRINT RESULTS
# ============================================================

passed = 0
failed = 0

for name, result in checks:

    if result:
        print(f"✅ PASS  | {name}")
        passed += 1

    else:
        print(f"❌ FAIL  | {name}")
        failed += 1


print("\n" + "=" * 70)
print(f"PASSED : {passed}")
print(f"FAILED : {failed}")
print("=" * 70)

if failed == 0:
    print("\n🎉 ALL WORKFLOW TRANSITION CHECKS PASSED")
else:
    print("\n⚠️ SOME CHECKS FAILED")