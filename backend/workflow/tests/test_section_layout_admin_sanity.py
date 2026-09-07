"""
Sanity checks used during the Admin Section Layout Designer fix iteration.

This file is temporary. It exercises the designer GET view and the POST
save endpoint with minimal fixtures so the reviewer can reproduce failures
without running the full workflow suite.
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
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


class SectionLayoutAdminSanityTests(TestCase):
    def test_save_url_names_exist(self):
        user, workflow, step, form, section = make_section_workflow()

        self.assertEqual(
            reverse("admin:workflow_formsection_layout", args=[section.pk]),
            "/admin/workflow/formsection/%s/layout/" % section.pk,
        )
        self.assertEqual(
            reverse("admin:workflow_formsection_layout_save", args=[section.pk]),
            "/admin/workflow/formsection/%s/layout/save/" % section.pk,
        )

    def test_save_endpoint_exists_and_is_wired(self):
        user, workflow, step, form, section = make_section_workflow()

        field = FormField.objects.create(
            section=section,
            name="f1",
            code="f1",
            field_type=FormField.FieldType.TEXT,
            label="f1",
            order=1,
            is_active=True,
        )
        group = FormRepeatableGroup.objects.create(
            section=section,
            name="g1",
            code="g1",
            order=1,
            is_active=True,
        )

        client = Client(enforce_csrf_checks=True)
        client.force_login(user)

        save_url = reverse(
            "admin:workflow_formsection_layout_save", args=[section.pk]
        )
        resp = client.post(
            save_url,
            [
                {"type": "field", "id": field.id},
                {"type": "group", "id": group.id},
            ],
            HTTP_HOST="localhost",
            content_type="application/json",
        )
        self.assertNotEqual(resp.status_code, 404)

    def test_mixed_save_normalizes_layout_order(self):
        user, workflow, step, form, section = make_section_workflow()

        field_a = FormField.objects.create(
            section=section,
            name="field_a",
            code="field_a",
            field_type=FormField.FieldType.TEXT,
            label="field_a",
            order=1,
            is_active=True,
        )
        group_a = FormRepeatableGroup.objects.create(
            section=section,
            name="group_a",
            code="group_a",
            order=1,
            is_active=True,
        )
        field_b = FormField.objects.create(
            section=section,
            name="field_b",
            code="field_b",
            field_type=FormField.FieldType.TEXT,
            label="field_b",
            order=2,
            is_active=True,
        )
        group_b = FormRepeatableGroup.objects.create(
            section=section,
            name="group_b",
            code="group_b",
            order=2,
            is_active=True,
        )

        client = Client(enforce_csrf_checks=True)
        client.force_login(user)

        get_url = reverse("admin:workflow_formsection_layout", args=[section.pk])
        save_url = reverse(
            "admin:workflow_formsection_layout_save", args=[section.pk]
        )

        token_match = client.get(get_url, HTTP_HOST="localhost").content.decode(
            "utf-8"
        )
        import re

        match = re.search(
            r'name="csrfmiddlewaretoken"[^>]*value="([^"]+)"', token_match
        )
        csrf_token = match.group(1) if match else None
        self.assertIsNotNone(csrf_token)

        resp = client.post(
            save_url,
            [
                {"type": "group", "id": group_a.id},
                {"type": "field", "id": field_b.id},
                {"type": "field", "id": field_a.id},
                {"type": "group", "id": group_b.id},
            ],
            HTTP_HOST="localhost",
            content_type="application/json",
            data={"csrfmiddlewaretoken": csrf_token},
        )
        self.assertEqual(resp.status_code, 200, resp.content.decode("utf-8"))

        field_a.refresh_from_db()
        field_b.refresh_from_db()
        group_a.refresh_from_db()
        group_b.refresh_from_db()

        self.assertEqual(field_a.layout_order, 30)
        self.assertEqual(field_b.layout_order, 20)
        self.assertEqual(group_a.layout_order, 10)
        self.assertEqual(group_b.layout_order, 40)

        self.assertEqual(field_a.order, 1)
        self.assertEqual(field_b.order, 2)
        self.assertEqual(group_a.order, 1)
        self.assertEqual(group_b.order, 2)
