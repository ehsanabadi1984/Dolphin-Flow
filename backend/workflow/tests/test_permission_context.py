from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.models import (
    FieldAccess,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    RepeatableGroupAccess,
    Workflow,
    WorkflowMembership,
    WorkflowStep,
)
from workflow.permission_context import (
    FieldPermission,
    GroupPermission,
    PermissionContext,
)


class PermissionContextTests(TestCase):

    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username="permission-user",
            password="password",
        )
        self.other_user = self.User.objects.create_user(
            username="other-user",
            password="password",
        )

        self.workflow = Workflow.objects.create(
            name="Permission Workflow",
            code="PERMISSION_WF",
        )
        self.step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Permission Step",
            code="PERMISSION_STEP",
            order=1,
        )
        self.other_step = WorkflowStep.objects.create(
            workflow=self.workflow,
            name="Other Step",
            code="OTHER_STEP",
            order=2,
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Permission Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Permission Section",
            code="PERMISSION",
            order=1,
        )

        self.normal_field = FormField.objects.create(
            section=self.section,
            name="Normal",
            code="NORMAL",
            label="Normal",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )

        self.group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="ITEMS",
            order=2,
        )

        self.repeatable_field = FormField.objects.create(
            section=self.section,
            repeatable_group=self.group,
            name="Repeatable",
            code="REPEATABLE",
            label="Repeatable",
            field_type=FormField.FieldType.TEXT,
            order=1,
        )

    def build(self):
        return PermissionContext.build(
            workflow=self.workflow,
            form=self.form,
            step=self.step,
            user=self.user,
        )

    def add_membership(self, role):
        return WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=role,
            is_active=True,
        )

    def test_missing_permissions_default_to_deny(self):
        context = self.build()

        self.assertEqual(
            context.field(self.normal_field),
            FieldPermission(False, False),
        )
        self.assertEqual(
            context.field(self.repeatable_field),
            FieldPermission(False, False),
        )
        self.assertEqual(
            context.group(self.group),
            GroupPermission(False, False, False, False),
        )

    def test_field_user_rule_overrides_role_rules(self):
        self.add_membership(
            WorkflowMembership.Role.EXECUTOR,
        )
        FieldAccess.objects.create(
            field=self.normal_field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=self.normal_field,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=False,
        )

        context = self.build()

        self.assertEqual(
            context.field(self.normal_field),
            FieldPermission(True, False),
        )

    def test_field_role_rules_are_aggregated(self):
        self.add_membership(
            WorkflowMembership.Role.EXECUTOR,
        )
        self.add_membership(
            WorkflowMembership.Role.MANAGER,
        )
        FieldAccess.objects.create(
            field=self.normal_field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=False,
            can_edit=False,
        )
        FieldAccess.objects.create(
            field=self.normal_field,
            step=self.step,
            role=WorkflowMembership.Role.MANAGER,
            can_view=True,
            can_edit=True,
        )

        context = self.build()

        self.assertEqual(
            context.field(self.normal_field),
            FieldPermission(True, True),
        )

    def test_field_user_rule_with_deny_blocks_role_allow(self):
        self.add_membership(
            WorkflowMembership.Role.EXECUTOR,
        )
        FieldAccess.objects.create(
            field=self.normal_field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )
        FieldAccess.objects.create(
            field=self.normal_field,
            step=self.step,
            user=self.user,
            can_view=False,
            can_edit=False,
        )

        context = self.build()

        self.assertEqual(
            context.field(self.normal_field),
            FieldPermission(False, False),
        )

    def test_group_user_rule_overrides_role_rules(self):
        self.add_membership(
            WorkflowMembership.Role.EXECUTOR,
        )
        RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            user=self.user,
            can_view=True,
            can_edit=True,
            can_add=False,
            can_delete=False,
        )

        context = self.build()

        self.assertEqual(
            context.group(self.group),
            GroupPermission(True, True, False, False),
        )

    def test_group_role_rules_are_aggregated_per_action(self):
        self.add_membership(
            WorkflowMembership.Role.EXECUTOR,
        )
        self.add_membership(
            WorkflowMembership.Role.MANAGER,
        )
        RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=False,
            can_add=False,
            can_delete=True,
        )
        RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.MANAGER,
            can_view=False,
            can_edit=True,
            can_add=True,
            can_delete=False,
        )

        context = self.build()

        self.assertEqual(
            context.group(self.group),
            GroupPermission(True, True, True, True),
        )

    def test_rules_from_another_step_are_ignored(self):
        self.add_membership(
            WorkflowMembership.Role.EXECUTOR,
        )
        FieldAccess.objects.create(
            field=self.normal_field,
            step=self.other_step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )
        RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.other_step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

        context = self.build()

        self.assertEqual(
            context.field(self.normal_field),
            FieldPermission(False, False),
        )
        self.assertEqual(
            context.group(self.group),
            GroupPermission(False, False, False, False),
        )

    def test_inactive_fields_and_groups_are_not_in_snapshot(self):
        inactive_field = FormField.objects.create(
            section=self.section,
            name="Inactive",
            code="INACTIVE",
            label="Inactive",
            field_type=FormField.FieldType.TEXT,
            order=3,
            is_active=False,
        )
        inactive_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Inactive Group",
            code="INACTIVE_GROUP",
            order=4,
            is_active=False,
        )
        self.add_membership(
            WorkflowMembership.Role.EXECUTOR,
        )
        FieldAccess.objects.create(
            field=inactive_field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )
        RepeatableGroupAccess.objects.create(
            group=inactive_group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )

        context = self.build()

        self.assertNotIn(inactive_field.pk, context.normal_fields)
        self.assertNotIn(inactive_group.pk, context.groups)

    def test_active_membership_roles_only(self):
        WorkflowMembership.objects.create(
            workflow=self.workflow,
            user=self.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=False,
        )
        FieldAccess.objects.create(
            field=self.normal_field,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
        )

        context = self.build()

        self.assertEqual(context.roles, frozenset())
        self.assertEqual(
            context.field(self.normal_field),
            FieldPermission(False, False),
        )
