"""
Tests for the mixed top-level section layout feature.

Covers the new ``layout_order`` fields on ``FormField`` and
``FormRepeatableGroup``, the ``layout_items`` display collection built
by ``DynamicFormService.get_form_for_step``, and the backfill behavior
of migration 0048.
"""

from importlib import import_module

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.db import IntegrityError, models, transaction
from django.test import TestCase

from workflow.form_services import DynamicFormService
from workflow.models import (
    FieldAccess,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableGroupAccess,
    Workflow,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowStep,
    WorkflowStepExecution,
)


User = get_user_model()


def create_service_environment():
    """
    Build the minimal workflow/step/instance/form/section environment
    required by ``DynamicFormService.get_form_for_step``.
    """
    user = User.objects.create_user(
        username="layout_test_user",
        password="test-password",
    )

    workflow = Workflow.objects.create(
        name="Layout Test Workflow",
        code="LAYOUT_TEST_WORKFLOW",
        is_active=True,
    )

    step = WorkflowStep.objects.create(
        workflow=workflow,
        name="Layout Step",
        code="LAYOUT_STEP",
        order=1,
        is_active=True,
    )

    WorkflowMembership.objects.create(
        workflow=workflow,
        user=user,
        role=WorkflowMembership.Role.EXECUTOR,
        is_active=True,
    )

    form = FormDefinition.objects.create(
        workflow=workflow,
        name="Layout Test Form",
        is_active=True,
    )

    section = FormSection.objects.create(
        form=form,
        name="Layout Section",
        code="LAYOUT_SECTION",
        order=1,
        is_active=True,
    )

    instance = WorkflowInstance.objects.create(
        workflow=workflow,
        current_step=step,
        status=WorkflowInstance.Status.ACTIVE,
    )

    WorkflowStepExecution.objects.create(
        instance=instance,
        workflow_step=step,
        performed_by=user,
    )

    return user, workflow, step, instance, form, section


def make_field(section, code, order, layout_order=None, **kwargs):
    return FormField.objects.create(
        section=section,
        name=code,
        code=code,
        field_type=FormField.FieldType.TEXT,
        label=code,
        order=order,
        layout_order=layout_order,
        is_active=True,
        **kwargs,
    )


def make_group(section, code, order, layout_order=None, **kwargs):
    return FormRepeatableGroup.objects.create(
        section=section,
        name=code,
        code=code,
        order=order,
        layout_order=layout_order,
        is_active=True,
        **kwargs,
    )


def grant_field_access(step, field):
    FieldAccess.objects.create(
        field=field,
        step=step,
        role=WorkflowMembership.Role.EXECUTOR,
        can_view=True,
        can_edit=True,
    )


def grant_group_access(step, group):
    RepeatableGroupAccess.objects.create(
        group=group,
        step=step,
        role=WorkflowMembership.Role.EXECUTOR,
        can_view=True,
        can_edit=True,
        can_add=True,
        can_delete=True,
    )


class LayoutOrderModelTests(TestCase):
    """Test A — both models expose the intended ``layout_order`` field."""

    def test_form_field_has_layout_order_field(self):
        field = FormField._meta.get_field("layout_order")

        self.assertIsInstance(field, models.PositiveIntegerField)
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
        self.assertFalse(field.unique)

    def test_form_repeatable_group_has_layout_order_field(self):
        field = FormRepeatableGroup._meta.get_field("layout_order")

        self.assertIsInstance(field, models.PositiveIntegerField)
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
        self.assertFalse(field.unique)

    def test_layout_order_defaults_to_null(self):
        _, _, _, _, _, section = create_service_environment()

        field = make_field(section, "plain_field", order=1)
        group = make_group(section, "plain_group", order=1)

        self.assertIsNone(field.layout_order)
        self.assertIsNone(group.layout_order)


class OrderIndependenceTests(TestCase):
    """Test B — existing ``order`` semantics remain fully independent."""

    def setUp(self):
        _, _, _, _, _, self.section = create_service_environment()

        # ``order`` and ``layout_order`` intentionally diverge.
        self.field_one = make_field(
            self.section,
            "field_one",
            order=1,
            layout_order=50,
        )
        self.field_two = make_field(
            self.section,
            "field_two",
            order=2,
            layout_order=10,
        )
        self.group_one = make_group(
            self.section,
            "group_one",
            order=1,
            layout_order=999,
        )
        self.group_two = make_group(
            self.section,
            "group_two",
            order=2,
            layout_order=5,
        )

    def test_meta_ordering_still_by_order(self):
        self.assertEqual(FormField._meta.ordering, ["order"])
        self.assertEqual(FormRepeatableGroup._meta.ordering, ["order"])

    def test_default_collection_order_is_still_order(self):
        fields = list(
            FormField.objects
            .filter(section=self.section, repeatable_group__isnull=True)
        )
        groups = list(
            FormRepeatableGroup.objects.filter(section=self.section)
        )

        self.assertEqual(
            [f.order for f in fields],
            [1, 2],
        )
        self.assertEqual(
            [g.order for g in groups],
            [1, 2],
        )
        self.assertEqual(
            [f.layout_order for f in fields],
            [50, 10],
        )

    def test_unique_form_field_order_constraint_unchanged(self):
        # Two top-level fields cannot share (section, order) even when
        # their layout_order values differ.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_field(
                    self.section,
                    "duplicate_order_field",
                    order=1,
                    layout_order=77,
                )

    def test_unique_repeatable_group_order_constraint_unchanged(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_group(
                    self.section,
                    "duplicate_order_group",
                    order=1,
                    layout_order=88,
                )


class MixedLayoutServiceTests(TestCase):
    """Tests C, D, E — ``layout_items`` in ``get_form_for_step``."""

    def setUp(self):
        (
            self.user,
            self.workflow,
            self.step,
            self.instance,
            self.form,
            self.section,
        ) = create_service_environment()

        # Field A / Group A / Field B / Group B / Field C with
        # intentionally mixed layout_order values: the layout must be
        # genuinely interleaved and independent of ``order``.
        self.field_a = make_field(
            self.section,
            "field_a",
            order=1,
            layout_order=10,
        )
        self.group_a = make_group(
            self.section,
            "group_a",
            order=1,
            layout_order=20,
        )
        self.field_b = make_field(
            self.section,
            "field_b",
            order=2,
            layout_order=30,
        )
        self.group_b = make_group(
            self.section,
            "group_b",
            order=2,
            layout_order=40,
        )
        self.field_c = make_field(
            self.section,
            "field_c",
            order=3,
            layout_order=50,
        )

        # Each NORMAL group needs at least one visible field or the
        # service treats it as non-renderable and skips it entirely.
        self.group_a_field = make_field(
            self.section,
            "group_a_field",
            order=1,
            layout_order=999,
            repeatable_group=self.group_a,
        )
        self.group_b_field = make_field(
            self.section,
            "group_b_field",
            order=1,
            layout_order=999,
            repeatable_group=self.group_b,
        )

        for field in (
            self.field_a,
            self.field_b,
            self.field_c,
            self.group_a_field,
            self.group_b_field,
        ):
            grant_field_access(self.step, field)

        for group in (
            self.group_a,
            self.group_b,
        ):
            grant_group_access(self.step, group)

    def _get_section(self):
        result = DynamicFormService.get_form_for_step(
            instance=self.instance,
            user=self.user,
            edit_mode=False,
        )

        self.assertEqual(len(result["sections"]), 1)

        return result["sections"][0]

    def test_mixed_layout_items_returned_in_layout_order(self):
        """Test C — fields and groups interleave by ``layout_order``."""
        section = self._get_section()

        layout_items = section["layout_items"]

        self.assertEqual(
            [item["type"] for item in layout_items],
            ["field", "group", "field", "group", "field"],
        )

        codes = []
        for item in layout_items:
            if item["type"] == "field":
                codes.append(item["item"]["field"].code)
            else:
                codes.append(item["item"]["group"].code)

        self.assertEqual(
            codes,
            ["field_a", "group_a", "field_b", "group_b", "field_c"],
        )

    def test_layout_items_ignore_order_semantics(self):
        """``order`` does not influence the mixed layout order."""
        section = self._get_section()

        codes = []
        for item in section["layout_items"]:
            if item["type"] == "field":
                codes.append(item["item"]["field"].code)
            else:
                codes.append(item["item"]["group"].code)

        # ``order`` is [1, 2, 3] for fields and [1, 2] for groups,
        # which would give "all fields then all groups" — the layout
        # must instead follow layout_order (10, 20, 30, 40, 50).
        self.assertNotEqual(
            codes,
            ["field_a", "field_b", "field_c", "group_a", "group_b"],
        )

    def test_layout_items_identify_each_item_type(self):
        section = self._get_section()

        self.assertEqual(
            set(item["type"] for item in section["layout_items"]),
            {"field", "group"},
        )

    def test_nested_group_fields_excluded_from_layout(self):
        """Test D — fields inside a repeatable group are not top-level."""
        # group_a_field is already nested inside Group A; add a second
        # nested field to make the exclusion obvious.
        nested_field = make_field(
            self.section,
            "nested_b",
            order=2,
            layout_order=1,
            repeatable_group=self.group_a,
        )
        grant_field_access(self.step, nested_field)

        section = self._get_section()

        codes = []
        for item in section["layout_items"]:
            if item["type"] == "field":
                codes.append(item["item"]["field"].code)
            else:
                codes.append(item["item"]["group"].code)

        # Only top-level fields appear in the layout; a layout_order
        # of 1 on a nested field must never lift it to the top level.
        self.assertNotIn("nested_b", codes)
        self.assertNotIn("group_a_field", codes)
        self.assertEqual(
            [code for code in codes if code.startswith("field_")],
            ["field_a", "field_b", "field_c"],
        )

        # The nested field still renders inside its group.
        group_a_data = next(
            group_data
            for group_data in section["repeatable_groups"]
            if group_data["group"] == self.group_a
        )
        nested_codes = [
            item["field"].code
            for item in group_a_data["fields"]
        ]
        self.assertIn("nested_b", nested_codes)

    def test_existing_collections_unchanged(self):
        """Test E — ``fields`` and ``repeatable_groups`` keep their shape."""
        section = self._get_section()

        self.assertEqual(
            set(section.keys()),
            {"section", "fields", "repeatable_groups", "layout_items"},
        )

        # ``fields`` still contains only top-level fields, in ``order``.
        self.assertEqual(
            [item["field"].code for item in section["fields"]],
            ["field_a", "field_b", "field_c"],
        )

        # ``repeatable_groups`` still contains groups in ``order``.
        self.assertEqual(
            [item["group"].code for item in section["repeatable_groups"]],
            ["group_a", "group_b"],
        )

        # Field data shape is untouched.
        first_field_data = section["fields"][0]
        self.assertEqual(first_field_data["field"], self.field_a)
        self.assertIn("can_edit", first_field_data)
        self.assertIn("value", first_field_data)
        self.assertIn("choices", first_field_data)

        # Group data shape is untouched.
        first_group_data = section["repeatable_groups"][0]
        self.assertEqual(first_group_data["group"], self.group_a)
        self.assertIn("fields", first_group_data)
        self.assertIn("items", first_group_data)
        self.assertIn("can_add", first_group_data)

        # Layout items reference the same underlying model objects.
        layout_field_codes = [
            item["item"]["field"]
            for item in section["layout_items"]
            if item["type"] == "field"
        ]
        self.assertEqual(
            layout_field_codes,
            [self.field_a, self.field_b, self.field_c],
        )

    def test_null_layout_order_sorts_last_deterministically(self):
        section = self._get_section()

        # Add an unpositioned field and group (layout_order NULL).
        new_field = make_field(
            self.section,
            "new_field",
            order=9,
        )
        new_group = make_group(
            self.section,
            "new_group",
            order=9,
        )
        new_group_field = make_field(
            self.section,
            "new_group_field",
            order=1,
            repeatable_group=new_group,
        )
        grant_field_access(self.step, new_field)
        grant_field_access(self.step, new_group_field)
        grant_group_access(self.step, new_group)

        section = self._get_section()

        types = [item["type"] for item in section["layout_items"]]

        # Both unpositioned items come after every positioned item.
        self.assertEqual(
            types[-2:],
            ["field", "group"],
        )

        codes = []
        for item in section["layout_items"]:
            if item["type"] == "field":
                codes.append(item["item"]["field"].code)
            else:
                codes.append(item["item"]["group"].code)

        self.assertEqual(
            codes[-2:],
            ["new_field", "new_group"],
        )


class LayoutOrderBackfillTests(TestCase):
    """Test F — migration backfill preserves the old display sequence."""

    def _run_backfill(self):
        migration_module = import_module(
            "workflow.migrations."
            "0048_formfield_layout_order_formrepeatablegroup_layout_order"
        )

        migration_module.backfill_layout_order(django_apps, None)

    def test_backfill_preserves_current_visual_order(self):
        _, _, _, _, _, section = create_service_environment()

        field_one = make_field(section, "field_one", order=1)
        field_two = make_field(section, "field_two", order=2)
        field_three = make_field(section, "field_three", order=3)
        group_one = make_group(section, "group_one", order=1)
        group_two = make_group(section, "group_two", order=2)

        self._run_backfill()

        field_one.refresh_from_db()
        field_two.refresh_from_db()
        field_three.refresh_from_db()
        group_one.refresh_from_db()
        group_two.refresh_from_db()

        # Fields first: 10, 20, 30 ... groups after: 100, 110, ...
        self.assertEqual(field_one.layout_order, 10)
        self.assertEqual(field_two.layout_order, 20)
        self.assertEqual(field_three.layout_order, 30)
        self.assertEqual(group_one.layout_order, 100)
        self.assertEqual(group_two.layout_order, 110)

        # Existing ``order`` values are untouched.
        self.assertEqual(field_one.order, 1)
        self.assertEqual(field_two.order, 2)
        self.assertEqual(field_three.order, 3)
        self.assertEqual(group_one.order, 1)
        self.assertEqual(group_two.order, 2)

    def test_backfill_skips_nested_group_fields(self):
        _, _, _, _, _, section = create_service_environment()

        top_field = make_field(section, "top_field", order=1)
        group = make_group(section, "group", order=1)
        nested_field = make_field(
            section,
            "nested_field",
            order=1,
            repeatable_group=group,
        )

        self._run_backfill()

        top_field.refresh_from_db()
        group.refresh_from_db()
        nested_field.refresh_from_db()

        self.assertEqual(top_field.layout_order, 10)
        self.assertEqual(group.layout_order, 100)
        self.assertIsNone(nested_field.layout_order)

    def test_backfill_group_range_never_collides_with_fields(self):
        _, _, _, _, _, section = create_service_environment()

        fields = [
            make_field(section, f"field_{index}", order=index + 1)
            for index in range(10)
        ]
        group = make_group(section, "group", order=1)

        self._run_backfill()

        for field in fields:
            field.refresh_from_db()
        group.refresh_from_db()

        # Field #10 receives 100; the group range must still start
        # above every field value.
        self.assertEqual(fields[9].layout_order, 100)
        self.assertEqual(group.layout_order, 110)
        self.assertTrue(
            all(f.layout_order < group.layout_order for f in fields)
        )