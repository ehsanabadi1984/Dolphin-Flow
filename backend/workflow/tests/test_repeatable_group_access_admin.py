"""
Regression tests: RepeatableGroupAccess.can_delete must be
configurable through the Django Admin UI.

The RepeatableGroupAccess model always had the can_delete field and
the Dynamic Form backend already enforces it for NORMAL repeatable
groups, but the RepeatableGroupAccessInline previously exposed only
can_view / can_edit / can_add. These tests prove the field is
rendered in the Admin form and can be toggled and persisted through
an actual Admin change-form POST.
"""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

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


class RepeatableGroupAccessAdminTests(TestCase):
    """Admin UI configurability of RepeatableGroupAccess.can_delete."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = User.objects.create_user(
            username="rga_admin_user",
            password="test-password",
            is_staff=True,
            is_superuser=True,
        )

        cls.workflow = Workflow.objects.create(
            name="RGA Admin Workflow",
            code="RGA_ADMIN_WF",
            is_active=True,
        )

        cls.step = WorkflowStep.objects.create(
            workflow=cls.workflow,
            name="Admin Test Step",
            code="ADMIN_TEST_STEP",
            order=1,
            is_active=True,
        )

        cls.form = FormDefinition.objects.create(
            workflow=cls.workflow,
            name="RGA Admin Form",
            is_active=True,
        )

        cls.section = FormSection.objects.create(
            form=cls.form,
            name="Admin Section",
            code="ADMIN_SECTION",
            order=1,
            is_active=True,
        )

        cls.group = FormRepeatableGroup.objects.create(
            section=cls.section,
            name="Admin Group",
            code="admin_group",
            order=1,
            is_active=True,
        )

        cls.access = RepeatableGroupAccess.objects.create(
            group=cls.group,
            step=cls.step,
            role=WorkflowMembership.Role.EXECUTOR,
            can_view=True,
            can_edit=True,
            can_add=True,
            can_delete=False,
        )

        cls.change_url = (
            f"/admin/workflow/formrepeatablegroup/"
            f"{cls.group.pk}/change/"
        )

    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.client.force_login(self.admin_user)

    def _get_change_page(self):
        resp = self.client.get(
            self.change_url,
            HTTP_HOST="localhost",
        )
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _access_prefix(self, html):
        """Return the inline formset prefix of the RepeatableGroupAccess
        inline, discovered from the rendered can_delete input."""
        match = re.search(
            r'name="([a-zA-Z_]+)-0-can_delete"',
            html,
        )
        self.assertIsNotNone(
            match,
            "can_delete input not found in rendered admin form",
        )
        prefix = match.group(1)
        return prefix

    def _empty_inline_management_data(self, html):
        """Return management-form fields for inlines that have no rows
        (e.g. the RepeatableField inline), so the admin accepts them."""
        access_prefix = self._access_prefix(html)

        prefixes = set(
            re.findall(
                r'name="([a-zA-Z_]+)-TOTAL_FORMS"',
                html,
            )
        )

        data = {}

        for prefix in prefixes:
            if prefix == access_prefix:
                continue

            data.update(
                {
                    f"{prefix}-TOTAL_FORMS": "0",
                    f"{prefix}-INITIAL_FORMS": "0",
                    f"{prefix}-MIN_NUM_FORMS": "0",
                    f"{prefix}-MAX_NUM_FORMS": "1000",
                }
            )

        return data

    def _base_post_data(self, html, *, can_delete_checked):
        prefix = self._access_prefix(html)

        post_data = {
            "section": self.section.pk,
            "name": self.group.name,
            "code": self.group.code,
            "group_type": self.group.group_type,
            "display_type": self.group.display_type,
            "description": self.group.description,
            "order": self.group.order,
            "is_required": "on",
            "is_active": "on",
            "_save": "Save",
        }

        post_data.update(
            self._empty_inline_management_data(html)
        )

        post_data.update(
            {
                f"{prefix}-TOTAL_FORMS": "1",
                f"{prefix}-INITIAL_FORMS": "1",
                f"{prefix}-MIN_NUM_FORMS": "0",
                f"{prefix}-MAX_NUM_FORMS": "1000",
                f"{prefix}-0-id": self.access.pk,
                f"{prefix}-0-group": self.group.pk,
                f"{prefix}-0-step": self.step.pk,
                f"{prefix}-0-role": WorkflowMembership.Role.EXECUTOR,
                f"{prefix}-0-user": "",
                f"{prefix}-0-can_view": "on",
                f"{prefix}-0-can_edit": "on",
                f"{prefix}-0-can_add": "on",
            }
        )

        if can_delete_checked:
            post_data[f"{prefix}-0-can_delete"] = "on"

        return post_data

    def _save_via_admin(self, *, can_delete_checked):
        html = self._get_change_page()

        post_data = self._base_post_data(
            html,
            can_delete_checked=can_delete_checked,
        )

        resp = self.client.post(
            self.change_url,
            post_data,
            HTTP_HOST="localhost",
        )

        # Admin redirects to the changelist on success.
        self.assertEqual(
            resp.status_code,
            302,
            msg=resp.content.decode(),
        )

    def test_can_delete_rendered_in_admin_form(self):
        """The group change page must render the can_delete inline field."""
        html = self._get_change_page()

        prefix = self._access_prefix(html)

        self.assertIn(
            f'name="{prefix}-0-can_delete"',
            html,
        )
        self.assertIn(
            f'id="id_{prefix}-0-can_delete"',
            html,
        )

        # The other permissions must still be present.
        for permission in (
            "can_view",
            "can_edit",
            "can_add",
        ):
            self.assertIn(
                f'id="id_{prefix}-0-{permission}"',
                html,
            )

    def test_can_delete_can_be_set_true_and_saved(self):
        """POSTing the admin change form with can_delete checked must
        persist can_delete=True."""
        self.assertFalse(self.access.can_delete)

        self._save_via_admin(
            can_delete_checked=True,
        )

        self.access.refresh_from_db()
        self.assertTrue(self.access.can_delete)

    def test_can_delete_read_back_true_after_admin_save(self):
        """After an admin save with can_delete=True, the change page
        renders the checkbox checked and the DB keeps the value."""
        self._save_via_admin(
            can_delete_checked=True,
        )

        html = self._get_change_page()
        prefix = self._access_prefix(html)

        # The checkbox input for this row must be rendered as checked.
        checkbox_match = re.search(
            (
                rf'<input[^>]*name="{prefix}-0-can_delete"'
                rf"[^>]*>"
            ),
            html,
        )
        self.assertIsNotNone(checkbox_match)
        self.assertIn(
            "checked",
            checkbox_match.group(),
        )

        # And the DB value is still True after a fresh read.
        access_from_db = RepeatableGroupAccess.objects.get(
            pk=self.access.pk,
        )
        self.assertTrue(access_from_db.can_delete)

    def test_can_delete_unchecked_saved_through_admin(self):
        """Leaving can_delete unchecked in the admin form persists False."""
        self.access.can_delete = True
        self.access.save(update_fields=["can_delete"])

        self._save_via_admin(
            can_delete_checked=False,
        )

        self.access.refresh_from_db()
        self.assertFalse(self.access.can_delete)
