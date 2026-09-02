from django.contrib.auth import get_user_model
from django.test import TestCase

from workflow.models import (
    FormDefinition,
    FormRepeatableGroup,
    FormSection,
    RepeatableGroupAccess,
    Workflow,
    WorkflowMembership,
    WorkflowStep,
)

User = get_user_model()


class RepeatableGroupAccessModelTests(TestCase):
    """Tests for the RepeatableGroupAccess model, specifically the can_delete field."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username="rga_test_user",
            password="test-password",
        )

        cls.workflow = Workflow.objects.create(
            name="RGA Test Workflow",
            code="RGA_TEST_WF",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Test Step",
            code="TEST_STEP",
            order=1,
            is_active=True,
        )

        cls.membership = WorkflowMembership.objects.create(
            workflow=cls.workflow,
            user=cls.user,
            role=WorkflowMembership.Role.EXECUTOR,
            is_active=True,
        )

        cls.form = FormDefinition.objects.create(
            workflow=cls.workflow,
            name="RGA Test Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Test Section",
            code="TEST_SECTION",
            order=1,
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Test Group",
            code="test_group",
            order=1,
            is_active=True,
        )

    def test_can_delete_field_exists(self):
        """RepeatableGroupAccess must have a can_delete field."""
        access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=False,
        )
        self.assertTrue(hasattr(access, "can_delete"))

    def test_can_delete_default_is_false(self):
        """can_delete must default to False for safety."""
        access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
        )
        self.assertFalse(access.can_delete)

    def test_can_delete_can_be_set_true(self):
        """can_delete can be explicitly set to True."""
        access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_delete=True,
        )
        access.refresh_from_db()
        self.assertTrue(access.can_delete)

    def test_can_delete_can_be_set_false(self):
        """can_delete can be explicitly set to False."""
        access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_delete=False,
        )
        access.refresh_from_db()
        self.assertFalse(access.can_delete)

    def test_can_delete_independent_of_other_permissions(self):
        """can_delete is independent of can_view, can_edit, and can_add."""
        access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=True,
        )
        self.assertTrue(access.can_view)
        self.assertTrue(access.can_edit)
        self.assertTrue(access.can_add)
        self.assertTrue(access.can_delete)

    def test_existing_access_rules_have_can_delete_false(self):
        """Any RepeatableGroupAccess created without specifying can_delete gets False."""
        access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=False,
            can_add=False,
        )
        self.assertFalse(access.can_delete)

    def test_can_delete_persists_in_database(self):
        """can_delete value persists across save/load cycles."""
        access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_delete=True,
        )

        access.refresh_from_db()
        self.assertTrue(access.can_delete)

        # Simulate reload from database
        access_from_db = RepeatableGroupAccess.objects.get(pk=access.pk)
        self.assertTrue(access_from_db.can_delete)

    def test_user_rule_can_delete_independent_of_role_rule(self):
        """A user-specific rule can have can_delete=True while role rule has False."""
        role_access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_delete=False,
        )

        user_access = RepeatableGroupAccess.objects.create(
            group=self.group,
            step=self.step,
            user=self.user,
            can_delete=True,
        )

        self.assertFalse(role_access.can_delete)
        self.assertTrue(user_access.can_delete)
