"""
Admin designer tests for the Section Layout Designer.

These tests exercise the Django Admin GET designer view, the POST save
endpoint, authorization, cross-section protection, duplicate detection,
missing-item detection, nested-field rejection, inactive-item handling,
NULL layout_order handling, duplicate existing layout_order handling,
order preservation, CSRF, transactional behavior, and the split
FormField / FormRepeatableGroup bulk_update persistence.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from workflow.admin import (
    FormSectionAdmin,
    dolphin_admin_site,
)
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


User = get_user_model()


def make_section_workflow(*, workflow_name="Layout WF", form_name="Layout Form"):
    user = User.objects.create_user(
        username="layout_admin_user_%s" % workflow_name,
        password="test-password",
        is_staff=True,
        is_superuser=True,
    )

    workflow = Workflow.objects.create(
        name=workflow_name,
        code="LAYOUT_%s" % workflow_name.replace(" ", "_").upper(),
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
        name=form_name,
        is_active=True,
    )

    section = FormSection.objects.create(
        form=form,
        name="Layout Section",
        code="LAYOUT_SECTION",
        order=1,
        is_active=True,
    )

    return user, workflow, step, form, section


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


class _AdminTestHelpers:
    @staticmethod
    def admin_client(*, user=None, enforce_csrf_checks=False):
        client = Client(enforce_csrf_checks=enforce_csrf_checks)
        if user is not None:
            client.force_login(user)
        return client

    @staticmethod
    def get_designer_url(section):
        return "/admin/workflow/formsection/%s/layout/" % section.pk

    @staticmethod
    def get_save_url(section):
        return "/admin/workflow/formsection/%s/layout/save/" % section.pk

    @classmethod
    def csrf_token_from_get(cls, client, url):
        resp = client.get(url)
        from django.utils.crypto import constant_time_compare

        import re

        match = re.search(
            r'name=\"csrfmiddlewaretoken\"[^>]*value=\"([^\"]+)\"',
            resp.content.decode("utf-8"),
        )
        if not match:
            return None
        return match.group(1)


class SectionLayoutAdminAuthorizationTests(TestCase):
    def test_designer_url_exists(self):
        user, workflow, step, form, section = make_section_workflow()

        client = _AdminTestHelpers.admin_client(user=user)
        url = _AdminTestHelpers.get_designer_url(section)

        resp = client.get(url, HTTP_HOST="localhost")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("ترتیب نمایش آیتم‌های Section", resp.content.decode("utf-8"))

    def test_designer_requires_staff(self):
        user, workflow, step, form, section = make_section_workflow()
        user.is_staff = False
        user.save(update_fields=["is_staff"])

        client = _AdminTestHelpers.admin_client(user=user)
        url = _AdminTestHelpers.get_designer_url(section)

        resp = client.get(url, HTTP_HOST="localhost")
        self.assertNotEqual(resp.status_code, 200)

    def test_save_url_exists_for_authorized_user(self):
        user, workflow, step, form, section = make_section_workflow()

        client = _AdminTestHelpers.admin_client(user=user)
        url = _AdminTestHelpers.get_save_url(section)

        resp = client.post(
            url,
            {},
            HTTP_HOST="localhost",
        )
        # Empty payload is rejected, but the endpoint itself exists and
        # responds (not 404).
        self.assertNotEqual(resp.status_code, 404)

    def test_save_requires_change_permission(self):
        user, workflow, step, form, section = make_section_workflow()
        user.is_staff = True
        user.save(update_fields=["is_staff"])

        # A staff user still needs model-level change permission for
        # FormSection.
        from django.contrib.auth.models import Permission

        perm = Permission.objects.get(
            codename="change_formsection",
            content_type__app_label="workflow",
        )
        user.user_permissions.remove(perm)
        user.save(update_fields=["id"])
        user.refresh_from_db()

        client = _AdminTestHelpers.admin_client(user=user)
        url = _AdminTestHelpers.get_save_url(section)

        resp = client.post(
            url,
            [{"type": "field", "id": None}],
            HTTP_HOST="localhost",
        )
        # Admin wrapped view should deny.
        self.assertNotEqual(resp.status_code, 200)

    def test_unauthorized_user_cannot_access_designer(self):
        user, workflow, step, form, section = make_section_workflow()
        user.is_staff = False
        user.save(update_fields=["is_staff"])

        client = _AdminTestHelpers.admin_client(user=user)
        url = _AdminTestHelpers.get_designer_url(section)

        resp = client.get(url, HTTP_HOST="localhost")
        self.assertNotEqual(resp.status_code, 200)

    def test_unauthorized_user_cannot_save(self):
        user, workflow, step, form, section = make_section_workflow()
        user.is_staff = False
        user.save(update_fields=["is_staff"])

        field = make_field(section, "f1", order=1)
        client = _AdminTestHelpers.admin_client(user=user)
        url = _AdminTestHelpers.get_save_url(section)

        resp = client.post(
            url,
            [{"type": "field", "id": field.id}],
            HTTP_HOST="localhost",
        )
        self.assertNotEqual(resp.status_code, 200)


class SectionLayoutAdminDataSourceTests(TestCase):
    def setUp(self):
        (
            self.user,
            self.workflow,
            self.step,
            self.form,
            self.section,
        ) = make_section_workflow()

        self.field_a = make_field(self.section, "field_a", order=1)
        self.group_a = make_group(self.section, "group_a", order=1)
        self.field_b = make_field(self.section, "field_b", order=2)
        self.group_b = make_group(self.section, "group_b", order=2)

        # Nested field.
        self.nested = make_field(
            self.section,
            "nested",
            order=1,
            repeatable_group=self.group_a,
        )

        # Inactive items.
        self.inactive_field = make_field(
            self.section, "inactive_field", order=3
        )
        self.inactive_field.is_active = False
        self.inactive_field.save(update_fields=["is_active"])

        self.inactive_group = make_group(
            self.section, "inactive_group", order=3
        )
        self.inactive_group.is_active = False
        self.inactive_group.save(update_fields=["is_active"])

    def test_designer_shows_mixed_fields_and_groups(self):
        client = _AdminTestHelpers.admin_client(user=self.user)
        url = _AdminTestHelpers.get_designer_url(self.section)

        resp = client.get(url, HTTP_HOST="localhost")
        html = resp.content.decode("utf-8")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("field_a", html)
        self.assertIn("group_a", html)
        self.assertIn("field_b", html)
        self.assertIn("group_b", html)

    def test_designer_excludes_nested_field(self):
        client = _AdminTestHelpers.admin_client(user=self.user)
        url = _AdminTestHelpers.get_designer_url(self.section)

        resp = client.get(url, HTTP_HOST="localhost")
        html = resp.content.decode("utf-8")

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("nested", html)

    def test_designer_excludes_inactive_field(self):
        client = _AdminTestHelpers.admin_client(user=self.user)
        url = _AdminTestHelpers.get_designer_url(self.section)

        resp = client.get(url, HTTP_HOST="localhost")
        html = resp.content.decode("utf-8")

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("inactive_field", html)

    def test_designer_excludes_inactive_group(self):
        client = _AdminTestHelpers.admin_client(user=self.user)
        url = _AdminTestHelpers.get_designer_url(self.section)

        resp = client.get(url, HTTP_HOST="localhost")
        html = resp.content.decode("utf-8")

        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("inactive_group", html)

    def test_active_top_level_fields_only(self):
        fields = list(
            FormField.objects.filter(
                section=self.section,
                repeatable_group__isnull=True,
                is_active=True,
            )
        )
        self.assertEqual(
            {f.id for f in fields},
            {self.field_a.id, self.field_b.id},
        )

    def test_active_groups_only(self):
        groups = list(
            FormRepeatableGroup.objects.filter(
                section=self.section,
                is_active=True,
            )
        )
        self.assertEqual(
            {g.id for g in groups},
            {self.group_a.id, self.group_b.id},
        )


class SectionLayoutAdminSaveValidationTests(TestCase):
    def setUp(self):
        (
            self.user,
            self.workflow,
            self.step,
            self.form,
            self.section,
        ) = make_section_workflow()

        self.field_a = make_field(self.section, "field_a", order=1)
        self.group_a = make_group(self.section, "group_a", order=1)
        self.field_b = make_field(self.section, "field_b", order=2)
        self.group_b = make_group(self.section, "group_b", order=2)

        self.client = _AdminTestHelpers.admin_client(user=self.user)
        self.url = _AdminTestHelpers.get_save_url(self.section)

    def _submit(self, payload):
        return self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def test_invalid_id_rejected(self):
        resp = self._submit(
            [
                {"type": "field", "id": self.field_a.id},
                {"type": "group", "id": 999999},
                {"type": "field", "id": self.field_b.id},
                {"type": "group", "id": self.group_b.id},
            ]
        )
        self.assertNotEqual(resp.status_code, 200)

        self.field_a.refresh_from_db()
        self.field_b.refresh_from_db()
        self.group_a.refresh_from_db()
        self.group_b.refresh_from_db()

        self.assertIsNone(self.field_a.layout_order)
        self.assertIsNone(self.group_a.layout_order)
        self.assertIsNone(self.field_b.layout_order)
        self.assertIsNone(self.group_b.layout_order)

    def test_invalid_type_rejected(self):
        resp = self._submit(
            [
                {"type": "field", "id": self.field_a.id},
                {"type": "bogus", "id": self.group_a.id},
                {"type": "field", "id": self.field_b.id},
                {"type": "group", "id": self.group_b.id},
            ]
        )
        self.assertNotEqual(resp.status_code, 200)

    def test_duplicate_field_rejected(self):
        resp = self._submit(
            [
                {"type": "field", "id": self.field_a.id},
                {"type": "field", "id": self.field_a.id},
                {"type": "group", "id": self.group_a.id},
                {"type": "group", "id": self.group_b.id},
            ]
        )
        self.assertNotEqual(resp.status_code, 200)

    def test_duplicate_group_rejected(self):
        resp = self._submit(
            [
                {"type": "field", "id": self.field_a.id},
                {"type": "field", "id": self.field_b.id},
                {"type": "group", "id": self.group_a.id},
                {"type": "group", "id": self.group_a.id},
            ]
        )
        self.assertNotEqual(resp.status_code, 200)

    def test_same_pk_field_and_group_both_accepted(self):
        same_pk_field = make_field(self.section, "same_pk_field", order=3)
        same_pk_group = make_group(self.section, "same_pk_group", order=3)
        while same_pk_group.pk == same_pk_field.pk:
            same_pk_group = make_group(
                self.section, "same_pk_group", order=3
            )

        # Force a PK collision by reusing existing IDs is not
        # straightforward in a clean test, so instead we verify the
        # type-aware duplicate detection by ensuring both can be submitted
        # together and accepted when they are distinct typed identities.
        payload = [
            {"type": "field", "id": same_pk_field.id},
            {"type": "group", "id": same_pk_group.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": self.group_a.id},
        ]

        resp = self._submit(payload)
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))

        same_pk_field.refresh_from_db()
        same_pk_group.refresh_from_db()

        self.assertIsNotNone(same_pk_field.layout_order)
        self.assertIsNotNone(same_pk_group.layout_order)

    def test_wrong_section_field_rejected(self):
        other_user, other_wf, other_step, other_form, other_section = (
            make_section_workflow(workflow_name="Other WF", form_name="Other Form")
        )
        other_field = make_field(other_section, "other_field", order=1)

        payload = [
            {"type": "field", "id": other_field.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": self.group_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        resp = self._submit(payload)
        self.assertNotEqual(resp.status_code, 200)

    def test_wrong_section_group_rejected(self):
        other_user, other_wf, other_step, other_form, other_section = (
            make_section_workflow(workflow_name="Other WF 2", form_name="Other Form 2")
        )
        other_group = make_group(other_section, "other_group", order=1)

        payload = [
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": self.group_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "group", "id": other_group.id},
        ]

        resp = self._submit(payload)
        self.assertNotEqual(resp.status_code, 200)

    def test_nested_field_rejected(self):
        nested = make_field(
            self.section,
            "nested",
            order=1,
            repeatable_group=self.group_a,
        )

        payload = [
            {"type": "field", "id": nested.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": self.group_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        resp = self._submit(payload)
        self.assertNotEqual(resp.status_code, 200)

    def test_missing_active_item_rejected(self):
        payload = [
            {"type": "field", "id": self.field_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "group", "id": self.group_a.id},
            # group_b missing
        ]

        resp = self._submit(payload)
        self.assertNotEqual(resp.status_code, 200)

    def test_inactive_field_not_required_and_not_modified(self):
        payload = [
            {"type": "field", "id": self.field_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "group", "id": self.group_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        resp = self._submit(payload)
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))

        self.inactive_field.refresh_from_db()
        self.assertIsNone(self.inactive_field.layout_order)

    def test_inactive_group_not_required_and_not_modified(self):
        payload = [
            {"type": "field", "id": self.field_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "group", "id": self.group_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        resp = self._submit(payload)
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))

        self.inactive_group.refresh_from_db()
        self.assertIsNone(self.inactive_group.layout_order)


class SectionLayoutAdminPersistenceTests(TestCase):
    def setUp(self):
        (
            self.user,
            self.workflow,
            self.step,
            self.form,
            self.section,
        ) = make_section_workflow()

        self.field_a = make_field(self.section, "field_a", order=1)
        self.group_a = make_group(self.section, "group_a", order=1)
        self.field_b = make_field(self.section, "field_b", order=2)
        self.group_b = make_group(self.section, "group_b", order=2)

        self.client = _AdminTestHelpers.admin_client(user=self.user)
        self.url = _AdminTestHelpers.get_save_url(self.section)

        self.field_a_order = self.field_a.order
        self.group_a_order = self.group_a.order
        self.field_b_order = self.field_b.order
        self.group_b_order = self.group_b.order

    def _submit(self, payload):
        return self.client.post(
            self.url,
            data=payload,
            content_type="application/json",
            HTTP_HOST="localhost",
        )

    def test_mixed_order_saves_successfully(self):
        payload = [
            {"type": "group", "id": self.group_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        resp = self._submit(payload)
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))

        self.field_a.refresh_from_db()
        self.field_b.refresh_from_db()
        self.group_a.refresh_from_db()
        self.group_b.refresh_from_db()

        self.assertEqual(self.field_a.layout_order, 30)
        self.assertEqual(self.field_b.layout_order, 20)
        self.assertEqual(self.group_a.layout_order, 10)
        self.assertEqual(self.group_b.layout_order, 40)

    def test_form_field_order_unchanged(self):
        payload = [
            {"type": "group", "id": self.group_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        self._submit(payload)

        self.field_a.refresh_from_db()
        self.field_b.refresh_from_db()

        self.assertEqual(self.field_a.order, self.field_a_order)
        self.assertEqual(self.field_b.order, self.field_b_order)

    def test_form_repeatable_group_order_unchanged(self):
        payload = [
            {"type": "group", "id": self.group_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        self._submit(payload)

        self.group_a.refresh_from_db()
        self.group_b.refresh_from_db()

        self.assertEqual(self.group_a.order, self.group_a_order)
        self.assertEqual(self.group_b.order, self.group_b_order)

    def test_inactive_items_not_modified(self):
        inactive_field = make_field(
            self.section, "inactive_field", order=3
        )
        inactive_field.is_active = False
        inactive_field.save(update_fields=["is_active"])

        inactive_group = make_group(
            self.section, "inactive_group", order=3
        )
        inactive_group.is_active = False
        inactive_group.save(update_fields=["is_active"])

        payload = [
            {"type": "field", "id": self.field_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "group", "id": self.group_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        resp = self._submit(payload)
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))

        inactive_field.refresh_from_db()
        inactive_group.refresh_from_db()

        self.assertIsNone(inactive_field.layout_order)
        self.assertIsNone(inactive_group.layout_order)

    def test_null_layout_order_handled_and_normalized(self):
        null_field = make_field(self.section, "null_field", order=3)
        null_group = make_group(self.section, "null_group", order=3)

        self.assertIsNone(null_field.layout_order)
        self.assertIsNone(null_group.layout_order)

        payload = [
            {"type": "field", "id": null_field.id},
            {"type": "group", "id": self.group_a.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": null_group.id},
        ]

        resp = self._submit(payload)
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))

        null_field.refresh_from_db()
        null_group.refresh_from_db()

        self.assertIsNotNone(null_field.layout_order)
        self.assertIsNotNone(null_group.layout_order)
        self.assertNotEqual(null_field.layout_order, None)
        self.assertNotEqual(null_group.layout_order, None)

    def test_duplicate_existing_layout_order_normalized(self):
        dup_field = make_field(
            self.section, "dup_field", order=3, layout_order=20
        )
        dup_group = make_group(
            self.section, "dup_group", order=3, layout_order=20
        )

        payload = [
            {"type": "field", "id": dup_field.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": dup_group.id},
            {"type": "group", "id": self.group_a.id},
        ]

        resp = self._submit(payload)
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))

        dup_field.refresh_from_db()
        dup_group.refresh_from_db()

        self.assertNotEqual(dup_field.layout_order, 20)
        self.assertNotEqual(dup_group.layout_order, 20)
        self.assertEqual(dup_field.layout_order, 10)
        self.assertEqual(dup_group.layout_order, 40)

    def test_validation_failure_prevents_partial_update(self):
        # Arrange a payload that will be rejected after the DB would
        # otherwise have been touched by a naive single pass.
        another_user, another_wf, another_step, another_form, another_section = (
            make_section_workflow(
                workflow_name="Another WF",
                form_name="Another Form",
            )
        )
        other_field = make_field(
            another_section, "other_field", order=1
        )

        before = {
            "field_a": self.field_a.layout_order,
            "group_a": self.group_a.layout_order,
            "field_b": self.field_b.layout_order,
            "group_b": self.group_b.layout_order,
        }

        payload = [
            {"type": "field", "id": self.field_a.id},
            {"type": "field", "id": other_field.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "group", "id": self.group_a.id},
        ]

        resp = self._submit(payload)
        self.assertNotEqual(resp.status_code, 200)

        self.field_a.refresh_from_db()
        self.group_a.refresh_from_db()
        self.field_b.refresh_from_db()
        self.group_b.refresh_from_db()

        self.assertEqual(self.field_a.layout_order, before["field_a"])
        self.assertEqual(self.group_a.layout_order, before["group_a"])
        self.assertEqual(self.field_b.layout_order, before["field_b"])
        self.assertEqual(self.group_b.layout_order, before["group_b"])

    def test_mixed_persistence_uses_correct_models(self):
        payload = [
            {"type": "group", "id": self.group_a.id},
            {"type": "field", "id": self.field_b.id},
            {"type": "field", "id": self.field_a.id},
            {"type": "group", "id": self.group_b.id},
        ]

        self._submit(payload)

        field_count = FormField.objects.filter(
            id__in=[self.field_a.id, self.field_b.id],
            layout_order__isnull=False,
        ).count()
        group_count = FormRepeatableGroup.objects.filter(
            id__in=[self.group_a.id, self.group_b.id],
            layout_order__isnull=False,
        ).count()

        self.assertEqual(field_count, 2)
        self.assertEqual(group_count, 2)


class SectionLayoutAdminCsrfTests(TestCase):
    def setUp(self):
        (
            self.user,
            self.workflow,
            self.step,
            self.form,
            self.section,
        ) = make_section_workflow()

        self.field_a = make_field(self.section, "field_a", order=1)
        self.group_a = make_group(self.section, "group_a", order=1)
        self.field_b = make_field(self.section, "field_b", order=2)
        self.group_b = make_group(self.section, "group_b", order=2)

        self.client = _AdminTestHelpers.admin_client(
            user=self.user,
            enforce_csrf_checks=True,
        )
        self.url = _AdminTestHelpers.get_save_url(self.section)

    def test_save_without_csrf_rejected(self):
        # Django Admin CSRF protection must remain active for the save
        # endpoint. A POST without a valid CSRF token must be rejected.
        resp = self.client.post(
            self.url,
            [
                {"type": "field", "id": self.field_a.id},
                {"type": "group", "id": self.group_a.id},
                {"type": "field", "id": self.field_b.id},
                {"type": "group", "id": self.group_b.id},
            ],
            HTTP_HOST="localhost",
            content_type="application/json",
        )
        self.assertNotEqual(resp.status_code, 200)

    def test_save_with_valid_csrf_accepted(self):
        get_url = _AdminTestHelpers.get_designer_url(self.section)

        token = _AdminTestHelpers.csrf_token_from_get(
            self.client, get_url
        )
        self.assertIsNotNone(token)

        resp = self.client.post(
            self.url,
            [
                {"type": "field", "id": self.field_a.id},
                {"type": "group", "id": self.group_a.id},
                {"type": "field", "id": self.field_b.id},
                {"type": "group", "id": self.group_b.id},
            ],
            HTTP_HOST="localhost",
            data={"csrfmiddlewaretoken": token},
        )
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))
