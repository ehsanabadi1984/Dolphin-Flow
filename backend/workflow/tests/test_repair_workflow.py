import os

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

import django

django.setup()

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

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


def create_repair_workflow():
    workflow = Workflow.objects.create(
        name="Repair Process Test",
        code="REPAIR_PROCESS_TEST",
        is_active=True,
    )

    receive = WorkflowStep.objects.create(
        workflow=workflow,
        name="دریافت دستگاه",
        code="RECEIVE",
        order=1,
        is_active=True,
    )

    register = WorkflowStep.objects.create(
        workflow=workflow,
        name="ثبت دستگاه",
        code="REGISTER",
        order=2,
        is_active=True,
    )

    warranty_check = WorkflowStep.objects.create(
        workflow=workflow,
        name="بررسی گارانتی",
        code="WARRANTY_CHECK",
        order=3,
        is_active=True,
    )

    repair = WorkflowStep.objects.create(
        workflow=workflow,
        name="تعمیر",
        code="REPAIR",
        order=4,
        is_active=True,
    )

    warehouse = WorkflowStep.objects.create(
        workflow=workflow,
        name="انبار",
        code="WAREHOUSE",
        order=5,
        is_active=True,
    )

    delivery = WorkflowStep.objects.create(
        workflow=workflow,
        name="تحویل",
        code="DELIVERY",
        order=6,
        is_active=True,
    )

    transitions = [
        (
            "RECEIVE_TO_REGISTER",
            "دریافت ← ثبت",
            receive,
            register,
        ),
        (
            "REGISTER_TO_WARRANTY",
            "ثبت ← بررسی گارانتی",
            register,
            warranty_check,
        ),
        (
            "WARRANTY_TO_REPAIR",
            "گارانتی ← تعمیر",
            warranty_check,
            repair,
        ),
        (
            "REPAIR_TO_WAREHOUSE",
            "تعمیر ← انبار",
            repair,
            warehouse,
        ),
        (
            "WAREHOUSE_TO_DELIVERY",
            "انبار ← تحویل",
            warehouse,
            delivery,
        ),
    ]

    created_transitions = {}

    for code, name, from_step, to_step in transitions:
        transition = WorkflowTransition.objects.create(
            workflow=workflow,
            name=name,
            code=code,
            from_step=from_step,
            to_step=to_step,
            is_active=True,
        )

        created_transitions[code] = transition

    return (
        workflow,
        receive,
        register,
        warranty_check,
        repair,
        warehouse,
        delivery,
        created_transitions,
    )


def grant_execute_permission(
    workflow,
    user,
):

    WorkflowMembership.objects.create(
        workflow=workflow,
        user=user,
        role=WorkflowMembership.Role.EXECUTOR,
        is_active=True,
    )
    WorkflowPermission.objects.create(
        workflow=workflow,
        user=user,
        action=WorkflowPermission.Action.EXECUTE,
        effect=WorkflowPermission.Effect.ALLOW,
    )


def grant_transition_permission(
    transition,
    user,
):
    WorkflowPermission.objects.create(
        workflow=transition.workflow,
        transition=transition,
        user=user,
        action=WorkflowPermission.Action.TRANSITION,
        effect=WorkflowPermission.Effect.ALLOW,
    )




class RepairWorkflowTests(TestCase):
    def test_repair_workflow_happy_path(self):
        user = User.objects.create_user(
            username="repair_workflow_user",
            password="test-password",
        )

        (
            workflow,
            receive,
            register,
            warranty_check,
            repair,
            warehouse,
            delivery,
            transitions,
        ) = create_repair_workflow()

        grant_execute_permission(
            workflow=workflow,
            user=user,
        )

        for transition in transitions.values():
            grant_transition_permission(
                transition=transition,
                user=user,
            )

        instance = WorkflowExecutionService.start_workflow(
            workflow=workflow,
            user=user,
            data={
                "customer": "Test Customer",
            },
        )

        assert instance.current_step_id == receive.pk
        assert instance.status == WorkflowInstance.Status.ACTIVE

        execution_order = [
            "RECEIVE_TO_REGISTER",
            "REGISTER_TO_WARRANTY",
            "WARRANTY_TO_REPAIR",
            "REPAIR_TO_WAREHOUSE",
            "WAREHOUSE_TO_DELIVERY",
        ]

        expected_steps = [
            register,
            warranty_check,
            repair,
            warehouse,
            delivery,
        ]

        for transition_code, expected_step in zip(
            execution_order,
            expected_steps,
        ):
            transition = transitions[transition_code]

            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=transition,
                user=user,
            )

            instance.refresh_from_db()

            assert (
                instance.current_step_id
                == expected_step.pk
            )

        assert (
            instance.status
            == WorkflowInstance.Status.COMPLETED
        )

        assert (
            WorkflowStepExecution.objects
            .filter(instance=instance)
            .count()
            == 6
        )

        assert (
            WorkflowTransitionExecution.objects
            .filter(instance=instance)
            .count()
            == 5
        )


    def test_repair_workflow_cannot_skip_current_step(self):
        user = User.objects.create_user(
            username="repair_skip_user",
            password="test-password",
        )

        (
            workflow,
            receive,
            register,
            warranty_check,
            repair,
            warehouse,
            delivery,
            transitions,
        ) = create_repair_workflow()

        grant_execute_permission(
            workflow=workflow,
            user=user,
        )

        for transition in transitions.values():
            grant_transition_permission(
                transition=transition,
                user=user,
            )

        instance = WorkflowExecutionService.start_workflow(
            workflow=workflow,
            user=user,
        )

        invalid_transition = transitions[
            "REGISTER_TO_WARRANTY"
        ]

        try:
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=invalid_transition,
                user=user,
            )

        except Exception:
            instance.refresh_from_db()

            assert (
                instance.current_step_id
                == receive.pk
            )

        else:
            raise AssertionError(
                "نباید امکان عبور از مرحله فعلی وجود داشته باشد."
            )


    def test_repair_workflow_requires_transition_permission(self):
        user = User.objects.create_user(
            username="repair_permission_user",
            password="test-password",
        )

        (
            workflow,
            receive,
            register,
            warranty_check,
            repair,
            warehouse,
            delivery,
            transitions,
        ) = create_repair_workflow()

        grant_execute_permission(
            workflow=workflow,
            user=user,
        )

        instance = WorkflowExecutionService.start_workflow(
            workflow=workflow,
            user=user,
        )

        transition = transitions[
            "RECEIVE_TO_REGISTER"
        ]

        try:
            WorkflowExecutionService.execute_transition(
                instance=instance,
                transition=transition,
                user=user,
            )

        except PermissionDenied:
            instance.refresh_from_db()

            assert (
                instance.current_step_id
                == receive.pk
            )

        else:
            raise AssertionError(
                "کاربر بدون مجوز Transition نباید بتواند مرحله را تغییر دهد."
            )
