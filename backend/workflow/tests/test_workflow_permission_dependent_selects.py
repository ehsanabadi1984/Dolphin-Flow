"""
Regression tests for WorkflowPermission admin dependent selects.

Verifies that the admin form for WorkflowPermission correctly shows
steps and transitions belonging to the selected workflow, and that
changing the workflow dynamically refreshes the dependent fields.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory, Client

from workflow.admin import (
    WorkflowPermissionAdminForm,
    WorkflowPermissionAdmin,
    dolphin_admin_site,
    workflow_dynamic_steps,
    workflow_dynamic_transitions,
)
from workflow.models import (
    Workflow,
    WorkflowMembership,
    WorkflowStep,
    WorkflowPermission,
    WorkflowTransition,
)

User = get_user_model()


class WorkflowPermissionFormQuerysetTests(TestCase):
    """Test the WorkflowPermissionAdminForm queryset behavior."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="perm_form_user",
            password="test-password",
        )

        # Workflow A with 2 steps, 1 transition
        self.wf_a = Workflow.objects.create(
            name="Workflow A",
            code="DEP_SEL_A",
            is_active=True,
        )
        self.step_a1 = WorkflowStep.objects.create(
            workflow=self.wf_a,
            name="Step A1",
            code="DEP_STEP_A1",
            order=1,
            is_active=True,
        )
        self.step_a2 = WorkflowStep.objects.create(
            workflow=self.wf_a,
            name="Step A2",
            code="DEP_STEP_A2",
            order=2,
            is_active=True,
        )
        self.trans_a = WorkflowTransition.objects.create(
            workflow=self.wf_a,
            from_step=self.step_a1,
            to_step=self.step_a2,
            name="A1 to A2",
            code="DEP_TRANS_A",
            is_active=True,
        )

        # Workflow B with 1 step, 1 transition
        self.wf_b = Workflow.objects.create(
            name="Workflow B",
            code="DEP_SEL_B",
            is_active=True,
        )
        self.step_b1 = WorkflowStep.objects.create(
            workflow=self.wf_b,
            name="Step B1",
            code="DEP_STEP_B1",
            order=1,
            is_active=True,
        )
        self.trans_b = WorkflowTransition.objects.create(
            workflow=self.wf_b,
            from_step=self.step_b1,
            to_step=None,
            name="B1 to Finish",
            code="DEP_TRANS_B",
            is_active=True,
        )

    def test_no_workflow_step_queryset_empty(self):
        """When no workflow is selected, step queryset is empty."""
        form = WorkflowPermissionAdminForm()
        self.assertEqual(
            form.fields["step"].queryset.count(),
            0,
        )

    def test_no_workflow_transition_queryset_empty(self):
        """When no workflow is selected, transition queryset is empty."""
        form = WorkflowPermissionAdminForm()
        self.assertEqual(
            form.fields["transition"].queryset.count(),
            0,
        )

    def test_workflow_a_only_shows_a_steps(self):
        """Selecting workflow A shows only A's steps."""
        form = WorkflowPermissionAdminForm(
            data={"workflow": self.wf_a.pk},
        )
        steps = form.fields["step"].queryset
        self.assertIn(self.step_a1, steps)
        self.assertIn(self.step_a2, steps)
        self.assertNotIn(self.step_b1, steps)

    def test_workflow_a_only_shows_a_transitions(self):
        """Selecting workflow A shows only A's transitions."""
        form = WorkflowPermissionAdminForm(
            data={"workflow": self.wf_a.pk},
        )
        transitions = form.fields["transition"].queryset
        self.assertIn(self.trans_a, transitions)
        self.assertNotIn(self.trans_b, transitions)

    def test_workflow_b_only_shows_b_steps(self):
        """Selecting workflow B shows only B's steps."""
        form = WorkflowPermissionAdminForm(
            data={"workflow": self.wf_b.pk},
        )
        steps = form.fields["step"].queryset
        self.assertIn(self.step_b1, steps)
        self.assertNotIn(self.step_a1, steps)
        self.assertNotIn(self.step_a2, steps)

    def test_workflow_b_only_shows_b_transitions(self):
        """Selecting workflow B shows only B's transitions."""
        form = WorkflowPermissionAdminForm(
            data={"workflow": self.wf_b.pk},
        )
        transitions = form.fields["transition"].queryset
        self.assertIn(self.trans_b, transitions)
        self.assertNotIn(self.trans_a, transitions)

    def test_changing_workflow_clears_stale_step(self):
        """A step from workflow A is rejected when workflow is B."""
        form = WorkflowPermissionAdminForm(
            data={
                "workflow": self.wf_b.pk,
                "step": self.step_a1.pk,
            },
        )
        # The form's clean() should reject step_a1 for wf_b
        self.assertFalse(form.is_valid())
        self.assertIn("step", form.errors)

    def test_changing_workflow_clears_stale_transition(self):
        """A transition from workflow A is rejected when workflow is B."""
        form = WorkflowPermissionAdminForm(
            data={
                "workflow": self.wf_b.pk,
                "transition": self.trans_a.pk,
            },
        )
        self.assertFalse(form.is_valid())
        self.assertIn("transition", form.errors)

    def test_edit_existing_permission_preserves_querysets(self):
        """Editing an existing permission shows the correct querysets
        for the saved workflow."""
        perm = WorkflowPermission.objects.create(
            workflow=self.wf_a,
            step=self.step_a1,
            user=self.user,
            action=WorkflowPermission.Action.VIEW,
            effect=WorkflowPermission.Effect.ALLOW,
        )
        form = WorkflowPermissionAdminForm(instance=perm)
        # Should contain wf_a's steps
        self.assertIn(self.step_a1, form.fields["step"].queryset)
        self.assertIn(self.step_a2, form.fields["step"].queryset)
        # Should not contain wf_b's steps
        self.assertNotIn(self.step_b1, form.fields["step"].queryset)

    def test_inactive_steps_excluded(self):
        """Inactive steps should not appear in the queryset."""
        self.step_a1.is_active = False
        self.step_a1.save(update_fields=["is_active"])

        form = WorkflowPermissionAdminForm(
            data={"workflow": self.wf_a.pk},
        )
        steps = form.fields["step"].queryset
        self.assertNotIn(self.step_a1, steps)
        self.assertIn(self.step_a2, steps)

    def test_inactive_transitions_excluded(self):
        """Inactive transitions should not appear in the queryset."""
        self.trans_a.is_active = False
        self.trans_a.save(update_fields=["is_active"])

        form = WorkflowPermissionAdminForm(
            data={"workflow": self.wf_a.pk},
        )
        transitions = form.fields["transition"].queryset
        self.assertNotIn(self.trans_a, transitions)

    def test_valid_permission_form_saves(self):
        """A correctly filled form saves without errors."""
        form = WorkflowPermissionAdminForm(
            data={
                "workflow": self.wf_a.pk,
                "step": self.step_a1.pk,
                "user": self.user.pk,
                "action": WorkflowPermission.Action.VIEW,
                "effect": WorkflowPermission.Effect.ALLOW,
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        perm = form.save()
        self.assertEqual(perm.workflow, self.wf_a)
        self.assertEqual(perm.step, self.step_a1)


class WorkflowPermissionAdminEndpointTests(TestCase):
    """Test the AJAX endpoints return correct data for the admin."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="perm_ajax_user",
            password="test-password",
            is_staff=True,
            is_superuser=True,
        )

        self.wf_a = Workflow.objects.create(
            name="AJAX WF A",
            code="AJAX_DEP_A",
            is_active=True,
        )
        self.step_a1 = WorkflowStep.objects.create(
            workflow=self.wf_a,
            name="AJAX Step A1",
            order=1,
            is_active=True,
        )
        self.trans_a = WorkflowTransition.objects.create(
            workflow=self.wf_a,
            from_step=self.step_a1,
            to_step=None,
            name="AJAX A1 Finish",
            is_active=True,
        )

        self.wf_b = Workflow.objects.create(
            name="AJAX WF B",
            code="AJAX_DEP_B",
            is_active=True,
        )
        self.step_b1 = WorkflowStep.objects.create(
            workflow=self.wf_b,
            name="AJAX Step B1",
            order=1,
            is_active=True,
        )

        self.client = Client(enforce_csrf_checks=False)
        self.client.force_login(self.user)

    def test_steps_endpoint_returns_a_steps(self):
        resp = self.client.get(
            f"/admin/workflow/dynamic/steps/?workflow_id={self.wf_a.pk}",
            HTTP_HOST="localhost",
        )
        data = resp.json()
        ids = [r["id"] for r in data["results"]]
        self.assertIn(self.step_a1.pk, ids)
        self.assertNotIn(self.step_b1.pk, ids)

    def test_steps_endpoint_returns_b_steps(self):
        resp = self.client.get(
            f"/admin/workflow/dynamic/steps/?workflow_id={self.wf_b.pk}",
            HTTP_HOST="localhost",
        )
        data = resp.json()
        ids = [r["id"] for r in data["results"]]
        self.assertIn(self.step_b1.pk, ids)
        self.assertNotIn(self.step_a1.pk, ids)

    def test_transitions_endpoint_returns_a_transitions(self):
        resp = self.client.get(
            f"/admin/workflow/dynamic/transitions/?workflow_id={self.wf_a.pk}",
            HTTP_HOST="localhost",
        )
        data = resp.json()
        ids = [r["id"] for r in data["results"]]
        self.assertIn(self.trans_a.pk, ids)

    def test_steps_endpoint_no_workflow_returns_empty(self):
        resp = self.client.get(
            "/admin/workflow/dynamic/steps/",
            HTTP_HOST="localhost",
        )
        data = resp.json()
        self.assertEqual(data["results"], [])

    def test_transitions_endpoint_no_workflow_returns_empty(self):
        resp = self.client.get(
            "/admin/workflow/dynamic/transitions/",
            HTTP_HOST="localhost",
        )
        data = resp.json()
        self.assertEqual(data["results"], [])


class WorkflowPermissionAdminPageTests(TestCase):
    """Test the rendered admin page includes correct elements."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="perm_page_user",
            password="test-password",
            is_staff=True,
            is_superuser=True,
        )
        self.client = Client(enforce_csrf_checks=False)
        self.client.force_login(self.user)

    def test_add_page_includes_js_and_autocomplete(self):
        """The add page includes the admin JS and the workflow
        autocomplete widget."""
        resp = self.client.get(
            "/admin/workflow/workflowpermission/add/",
            HTTP_HOST="localhost",
        )
        html = resp.content.decode()

        # JS is included
        self.assertIn("workflow-admin.js", html)

        # id_workflow exists with admin-autocomplete class
        self.assertIn('id="id_workflow"', html)
        self.assertIn("admin-autocomplete", html)

        # id_step and id_transition exist as selects
        self.assertIn('id="id_step"', html)
        self.assertIn('id="id_transition"', html)

    def test_add_page_step_transition_empty_initially(self):
        """On the add page, step and transition selects have no
        options (only the blank option)."""
        resp = self.client.get(
            "/admin/workflow/workflowpermission/add/",
            HTTP_HOST="localhost",
        )
        html = resp.content.decode()

        import re

        step_match = re.search(
            r'id="id_step".*?</select>', html, re.DOTALL
        )
        self.assertIsNotNone(step_match)
        options = re.findall(
            r'<option[^>]*value="(\d+)"',
            step_match.group(),
        )
        self.assertEqual(options, [])

        trans_match = re.search(
            r'id="id_transition".*?</select>', html, re.DOTALL
        )
        self.assertIsNotNone(trans_match)
        options = re.findall(
            r'<option[^>]*value="(\d+)"',
            trans_match.group(),
        )
        self.assertEqual(options, [])
