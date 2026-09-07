"""Targeted tests for the FormSection admin layout designer."""

import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.test import Client, TestCase
from django.urls import reverse

from workflow.admin import dolphin_admin_site
from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    Workflow,
)

User = get_user_model()


def make_section(code="ADMIN_LAYOUT_SECTION"):
    workflow = Workflow.objects.create(
        name=f"Workflow {code}",
        code=f"WF_{code}",
        is_active=True,
    )
    form = FormDefinition.objects.create(
        workflow=workflow,
        name=f"Form {code}",
        is_active=True,
    )
    return FormSection.objects.create(
        form=form,
        name=f"Section {code}",
        code=code,
        order=1,
        is_active=True,
    )


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


class SectionLayoutAdminTests(TestCase):
    def setUp(self):
        self.section = make_section()
        self.field_a = make_field(self.section, "field_a", order=1, layout_order=20)
        self.group_a = make_group(self.section, "group_a", order=2, layout_order=10)
        self.field_b = make_field(self.section, "field_b", order=3, layout_order=30)

        self.user = User.objects.create_user(
            username="section_layout_admin",
            password="test-password",
            is_staff=True,
        )
        content_type = ContentType.objects.get_for_model(FormSection)
        permission = Permission.objects.get(
            content_type=content_type,
            codename="change_formsection",
        )
        self.user.user_permissions.add(permission)
        self.client = Client()
        self.client.force_login(self.user)

    def layout_url(self):
        return reverse(
            "admin:workflow_formsection_layout",
            args=[self.section.pk],
        )

    def save_url(self):
        return reverse(
            "admin:workflow_formsection_layout_save",
            args=[self.section.pk],
        )

    def payload(self, *items):
        return [{"type": item_type, "id": item_id} for item_type, item_id in items]

    def post_layout(self, payload, client=None, **extra):
        return (client or self.client).post(
            self.save_url(),
            data=json.dumps(payload),
            content_type="application/json",
            **extra,
        )

    def test_layout_endpoint_exists_and_returns_designer(self):
        response = self.client.get(self.layout_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ترتیب نمایش آیتم‌های Section")
        self.assertContains(response, self.field_a.code)
        self.assertContains(response, self.group_a.code)
        self.assertContains(response, "ذخیره ترتیب")

    def test_layout_view_requires_staff_and_change_permission(self):
        anonymous = Client()
        response = anonymous.get(self.layout_url())
        self.assertEqual(response.status_code, 302)

        user_without_permission = User.objects.create_user(
            username="no_section_change",
            password="test-password",
            is_staff=True,
        )
        client = Client()
        client.force_login(user_without_permission)
        response = client.get(self.layout_url())
        self.assertEqual(response.status_code, 403)

    def test_designer_contains_only_active_top_level_items(self):
        inactive_field = make_field(self.section, "inactive_field", order=4, layout_order=40)
        inactive_field.is_active = False
        inactive_field.save(update_fields=["is_active"])

        inactive_group = make_group(self.section, "inactive_group", order=5, layout_order=50)
        inactive_group.is_active = False
        inactive_group.save(update_fields=["is_active"])

        nested_group = make_group(self.section, "nested_group", order=6, layout_order=60)
        nested_field = make_field(
            self.section,
            "nested_field",
            order=7,
            layout_order=70,
            repeatable_group=nested_group,
        )

        response = self.client.get(self.layout_url())
        content = response.content.decode("utf-8")

        self.assertIn(self.field_a.code, content)
        self.assertIn(self.field_b.code, content)
        self.assertIn(self.group_a.code, content)
        self.assertNotIn(inactive_field.code, content)
        self.assertNotIn(inactive_group.code, content)
        self.assertNotIn(nested_field.code, content)

    def test_designer_orders_by_layout_order_then_null_last(self):
        field_null = make_field(self.section, "field_null", order=8, layout_order=None)
        group_null = make_group(self.section, "group_null", order=9, layout_order=None)

        response = self.client.get(self.layout_url())
        content = response.content.decode("utf-8")

        positions = [
            content.index(code)
            for code in (
                self.group_a.code,
                self.field_a.code,
                self.field_b.code,
                field_null.code,
                group_null.code,
            )
        ]
        self.assertEqual(positions, sorted(positions))

    def test_valid_mixed_save_normalizes_layout_order_and_preserves_order(self):
        original_orders = {
            self.field_a.pk: self.field_a.order,
            self.group_a.pk: self.group_a.order,
            self.field_b.pk: self.field_b.order,
        }

        response = self.post_layout(
            self.payload(
                ("field", self.field_b.pk),
                ("group", self.group_a.pk),
                ("field", self.field_a.pk),
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True})

        self.field_a.refresh_from_db()
        self.group_a.refresh_from_db()
        self.field_b.refresh_from_db()

        self.assertEqual(self.field_b.layout_order, 10)
        self.assertEqual(self.group_a.layout_order, 20)
        self.assertEqual(self.field_a.layout_order, 30)
        self.assertEqual(self.field_a.order, original_orders[self.field_a.pk])
        self.assertEqual(self.group_a.order, original_orders[self.group_a.pk])
        self.assertEqual(self.field_b.order, original_orders[self.field_b.pk])

    def test_save_requires_post(self):
        response = self.client.get(self.save_url())
        self.assertEqual(response.status_code, 405)
        self.assertJSONEqual(response.content, {"error": "متد مجاز نیست."})

    def test_save_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = self.post_layout(
            self.payload(
                ("field", self.field_a.pk),
                ("group", self.group_a.pk),
                ("field", self.field_b.pk),
            ),
            client=client,
        )

        self.assertEqual(response.status_code, 403)

    def test_save_accepts_valid_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        designer_response = client.get(self.layout_url())
        token = designer_response.cookies["csrftoken"].value

        response = self.post_layout(
            self.payload(
                ("field", self.field_b.pk),
                ("group", self.group_a.pk),
                ("field", self.field_a.pk),
            ),
            client=client,
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True})

    def test_invalid_json_is_rejected(self):
        response = self.client.post(
            self.save_url(),
            data=b"{not-json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"error": "شیوه ارسال ترتیب نامعتبر است."})

    def test_non_list_payload_is_rejected(self):
        response = self.client.post(
            self.save_url(),
            data=json.dumps({"field": self.field_a.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"error": "ترتیب باید در قالب یک لیست ارسال شود."})

    def test_invalid_type_is_rejected_without_changes(self):
        before = list(
            FormField.objects.filter(pk=self.field_a.pk).values_list("layout_order", flat=True)
        )
        response = self.post_layout(
            [
                {"type": "unknown", "id": self.field_a.pk},
                {"type": "group", "id": self.group_a.pk},
                {"type": "field", "id": self.field_b.pk},
            ]
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"error": "نوع آیتم نامعتبر."})
        self.assertEqual(
            list(FormField.objects.filter(pk=self.field_a.pk).values_list("layout_order", flat=True)),
            before,
        )

    def test_duplicate_field_is_rejected(self):
        response = self.post_layout(
            self.payload(
                ("field", self.field_a.pk),
                ("field", self.field_a.pk),
                ("group", self.group_a.pk),
                ("field", self.field_b.pk),
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"error": "یک آیتم در ترتیب دو بار تکرار شده است."})

    def test_duplicate_group_is_rejected(self):
        response = self.post_layout(
            self.payload(
                ("group", self.group_a.pk),
                ("group", self.group_a.pk),
                ("field", self.field_a.pk),
                ("field", self.field_b.pk),
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"error": "یک آیتم در ترتیب دو بار تکرار شده است."})

    def test_missing_item_is_rejected(self):
        response = self.post_layout(
            self.payload(
                ("field", self.field_a.pk),
                ("group", self.group_a.pk),
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {"error": "مجموعه آیتم‌های ارسالی با ترکیب فعلی Section کاملاً همخوانی ندارد."},
        )

    def test_unknown_or_inactive_field_is_rejected(self):
        inactive = make_field(self.section, "inactive_save_field", order=10, layout_order=40)
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        response = self.post_layout(
            self.payload(
                ("field", self.field_a.pk),
                ("group", self.group_a.pk),
                ("field", self.field_b.pk),
                ("field", inactive.pk),
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"error": "فیلد نامعتبر یا غیرفعال است."})

    def test_inactive_item_does_not_change_existing_layout(self):
        inactive = make_field(self.section, "inactive_preserve", order=10, layout_order=90)
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        response = self.post_layout(
            self.payload(
                ("field", self.field_b.pk),
                ("group", self.group_a.pk),
                ("field", self.field_a.pk),
            )
        )
        self.assertEqual(response.status_code, 200)
        inactive.refresh_from_db()
        self.assertEqual(inactive.layout_order, 90)

    def test_nested_field_is_rejected(self):
        group = make_group(self.section, "nested_reject_group", order=10)
        nested = make_field(
            self.section,
            "nested_reject_field",
            order=11,
            repeatable_group=group,
        )

        response = self.post_layout(
            self.payload(
                ("field", self.field_a.pk),
                ("group", self.group_a.pk),
                ("field", self.field_b.pk),
                ("field", nested.pk),
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "فیلد نامعتبر یا غیرفعال است.",
        )

    def test_cross_section_injection_is_rejected(self):
        other_section = make_section("OTHER_ADMIN_LAYOUT_SECTION")
        other_field = make_field(other_section, "other_field", order=1)

        response = self.post_layout(
            self.payload(
                ("field", self.field_a.pk),
                ("group", self.group_a.pk),
                ("field", self.field_b.pk),
                ("field", other_field.pk),
            )
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(
            response.content,
            {"error": "فیلد نامعتبر یا غیرفعال است."},
        )

    def test_same_numeric_pk_for_field_and_group_is_typed_correctly(self):
        collision_pk = 999999

        field = FormField(
            pk=collision_pk,
            section=self.section,
            name="collision_field",
            code="collision_field",
            field_type=FormField.FieldType.TEXT,
            label="collision_field",
            order=20,
            layout_order=None,
            is_active=True,
        )
        field.save(force_insert=True)

        group = FormRepeatableGroup(
            pk=collision_pk,
            section=self.section,
            name="collision_group",
            code="collision_group",
            order=21,
            layout_order=None,
            is_active=True,
        )
        group.save(force_insert=True)

        response = self.post_layout(
            self.payload(
                ("field", self.field_a.pk),
                ("group", self.group_a.pk),
                ("field", self.field_b.pk),
                ("field", collision_pk),
                ("group", collision_pk),
            )
        )

        self.assertEqual(response.status_code, 200)

        field.refresh_from_db()
        group.refresh_from_db()
        self.group_a.refresh_from_db()

        self.assertEqual(field.layout_order, 40)
        self.assertEqual(self.group_a.layout_order, 20)
        self.assertEqual(group.layout_order, 50)
    def test_null_and_duplicate_existing_layout_orders_are_normalized(self):
        self.field_a.layout_order = None
        self.field_b.layout_order = 10
        self.group_a.layout_order = 10
        FormField.objects.bulk_update(
            [self.field_a, self.field_b],
            ["layout_order"],
        )
        FormRepeatableGroup.objects.bulk_update(
            [self.group_a],
            ["layout_order"],
        )

        response = self.post_layout(
            self.payload(
                ("group", self.group_a.pk),
                ("field", self.field_b.pk),
                ("field", self.field_a.pk),
            )
        )
        self.assertEqual(response.status_code, 200)
        self.field_a.refresh_from_db()
        self.field_b.refresh_from_db()
        self.group_a.refresh_from_db()
        self.assertEqual(self.group_a.layout_order, 10)
        self.assertEqual(self.field_b.layout_order, 20)
        self.assertEqual(self.field_a.layout_order, 30)

    def test_atomic_rollback_when_second_bulk_update_fails(self):
        original = {
            "field_a": self.field_a.layout_order,
            "field_b": self.field_b.layout_order,
            "group_a": self.group_a.layout_order,
        }

        with mock.patch.object(
            FormRepeatableGroup.objects,
            "bulk_update",
            side_effect=RuntimeError("forced test failure"),
        ):
            with self.assertRaises(RuntimeError):
                self.post_layout(
                    self.payload(
                        ("field", self.field_b.pk),
                        ("group", self.group_a.pk),
                        ("field", self.field_a.pk),
                    )
                )

        self.field_a.refresh_from_db()
        self.field_b.refresh_from_db()
        self.group_a.refresh_from_db()
        self.assertEqual(self.field_a.layout_order, original["field_a"])
        self.assertEqual(self.field_b.layout_order, original["field_b"])
        self.assertEqual(self.group_a.layout_order, original["group_a"])

    def test_save_endpoint_is_registered_on_dolphin_admin_site(self):
        names = {
            getattr(url_pattern, "name", None)
            for url_pattern in dolphin_admin_site._registry[FormSection].get_urls()
        }
        self.assertIn("workflow_formsection_layout", names)
        self.assertIn("workflow_formsection_layout_save", names)
