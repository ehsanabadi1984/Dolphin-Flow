import os
import django

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

django.setup()

from django.contrib.auth import get_user_model

from workflow.models import (
    Workflow,
    WorkflowMembership,
    WorkflowStep,
    FormDefinition,
    FormSection,
    FormField,
    FieldAccess,
)

from workflow.form_services import DynamicFormService


User = get_user_model()

TEST_WORKFLOW = "Dynamic Form Service Test"
USERNAME = "dynamic_form_test_user"


def reset_test_data():
    FieldAccess.objects.filter(
        field__section__form__workflow__name=TEST_WORKFLOW,
    ).delete()

    FormField.objects.filter(
        section__form__workflow__name=TEST_WORKFLOW,
    ).delete()

    FormSection.objects.filter(
        form__workflow__name=TEST_WORKFLOW,
    ).delete()

    FormDefinition.objects.filter(
        workflow__name=TEST_WORKFLOW,
    ).delete()

    WorkflowStep.objects.filter(
        workflow__name=TEST_WORKFLOW,
    ).delete()

    WorkflowMembership.objects.filter(
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
        code="DYNAMIC_FORM_SERVICE_TEST",
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

    form = FormDefinition.objects.create(
        workflow=workflow,
        name="Repair Form",
        is_active=True,
    )

    section = FormSection.objects.create(
        form=form,
        name="Device Information",
        code="DEVICE_INFO",
        order=1,
        is_active=True,
    )

    field_a = FormField.objects.create(
        section=section,
        name="IMEI",
        code="IMEI",
        field_type=FormField.FieldType.TEXT,
        label="IMEI",
        order=1,
        is_active=True,
    )

    field_b = FormField.objects.create(
        section=section,
        name="Problem",
        code="PROBLEM",
        field_type=FormField.FieldType.TEXTAREA,
        label="شرح مشکل",
        order=2,
        is_active=True,
    )

    field_c = FormField.objects.create(
        section=section,
        name="Repair Cost",
        code="REPAIR_COST",
        field_type=FormField.FieldType.NUMBER,
        label="هزینه تعمیر",
        order=3,
        is_active=True,
    )

    # ---------------------------------------------------------
    # Step One
    #
    # Field A -> VIEW + EDIT
    # Field B -> VIEW only
    # Field C -> hidden
    # ---------------------------------------------------------

    FieldAccess.objects.create(
        field=field_a,
        step=step_one,
        role=WorkflowMembership.Role.EXECUTOR,
        can_view=True,
        can_edit=True,
    )

    FieldAccess.objects.create(
        field=field_b,
        step=step_one,
        role=WorkflowMembership.Role.EXECUTOR,
        can_view=True,
        can_edit=False,
    )

    # ---------------------------------------------------------
    # Step Two
    #
    # Field A -> hidden
    # Field B -> VIEW + EDIT
    # Field C -> VIEW only
    # ---------------------------------------------------------

    FieldAccess.objects.create(
        field=field_b,
        step=step_two,
        role=WorkflowMembership.Role.EXECUTOR,
        can_view=True,
        can_edit=True,
    )

    FieldAccess.objects.create(
        field=field_c,
        step=step_two,
        role=WorkflowMembership.Role.EXECUTOR,
        can_view=True,
        can_edit=False,
    )

    return {
        "user": user,
        "workflow": workflow,
        "step_one": step_one,
        "step_two": step_two,
        "field_a": field_a,
        "field_b": field_b,
        "field_c": field_c,
    }


def get_field_codes(result):
    return [
        item["field"].code
        for section in result["sections"]
        for item in section["fields"]
    ]


def get_field(result, code):
    for section in result["sections"]:
        for item in section["fields"]:
            if item["field"].code == code:
                return item

    return None


def test_step_one(data):
    print("[TEST] 1. Dynamic form for Step One")

    result = DynamicFormService.get_form_for_step(
        workflow=data["workflow"],
        step=data["step_one"],
        user=data["user"],
    )

    assert result is not None

    codes = get_field_codes(result)

    imei = get_field(result, "IMEI")
    problem = get_field(result, "PROBLEM")
    repair_cost = get_field(result, "REPAIR_COST")

    assert "IMEI" in codes
    assert "PROBLEM" in codes
    assert "REPAIR_COST" not in codes

    assert imei["can_edit"] is True
    assert problem["can_edit"] is False
    assert repair_cost is None

    print("[PASS] Step One visibility is correct")
    print("[PASS] IMEI editable: True")
    print("[PASS] Problem read-only: True")
    print("[PASS] Repair cost hidden: True")


def test_step_two(data):
    print("[TEST] 2. Dynamic form for Step Two")

    result = DynamicFormService.get_form_for_step(
        workflow=data["workflow"],
        step=data["step_two"],
        user=data["user"],
    )

    assert result is not None

    codes = get_field_codes(result)

    imei = get_field(result, "IMEI")
    problem = get_field(result, "PROBLEM")
    repair_cost = get_field(result, "REPAIR_COST")

    assert "IMEI" not in codes
    assert "PROBLEM" in codes
    assert "REPAIR_COST" in codes

    assert imei is None
    assert problem["can_edit"] is True
    assert repair_cost["can_edit"] is False

    print("[PASS] Step Two visibility is correct")
    print("[PASS] IMEI hidden: True")
    print("[PASS] Problem editable: True")
    print("[PASS] Repair cost read-only: True")


def test_no_form(data):
    print("[TEST] 3. Workflow without FormDefinition")

    workflow = Workflow.objects.create(
        name="Dynamic Form Empty Test",
        code="DYNAMIC_FORM_EMPTY_TEST",
        is_active=True,
    )

    step = WorkflowStep.objects.create(
        workflow=workflow,
        name="Empty Step",
        code="EMPTY_STEP",
        order=1,
        is_active=True,
    )

    result = DynamicFormService.get_form_for_step(
        workflow=workflow,
        step=step,
        user=data["user"],
    )

    assert result is None

    print("[PASS] Missing form definition returns None")

    step.delete()
    workflow.delete()


def main():
    print("=" * 60)
    print("DYNAMIC FORM SERVICE TEST")
    print("=" * 60)

    reset_test_data()

    try:
        data = setup_data()

        test_step_one(data)
        test_step_two(data)
        test_no_form(data)

        print("=" * 60)
        print("DYNAMIC FORM SERVICE TEST PASSED")
        print("=" * 60)

    finally:
        reset_test_data()


if __name__ == "__main__":
    main()