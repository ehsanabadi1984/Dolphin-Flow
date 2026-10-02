from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, SimpleTestCase
from django.template.loader import get_template
from django.urls import resolve, reverse

from workflow.history_browser_service import HistoryBrowserService
from workflow.history_permissions import HISTORY_ACTION
from workflow.models import InstanceDevice
from operator_panel import history_views


class HistoryTemplateTests(SimpleTestCase):
    template_name = "operator_panel/history.html"

    def _field(self, label, *, display_value=None, value=None, file=None):
        return SimpleNamespace(
            display_label=label,
            label=label,
            display_value=display_value,
            value=value,
            file=file,
        )

    def _item(self, fields, child_groups=None):
        return SimpleNamespace(
            fields=fields,
            child_groups=child_groups or [],
        )

    def _group(self, name, items):
        return SimpleNamespace(name=name, items=items)

    def _render(self, snapshot):
        template = get_template(self.template_name)
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        request.resolver_match = SimpleNamespace(url_name="history", app_name="operator_panel")
        return template.render({
            "request": request,
            "history_title": "سوابق",
            "history_subtitle": "Workflow",
            "instance": SimpleNamespace(pk=1),
            "history": [
                SimpleNamespace(
                    execution=SimpleNamespace(
                        instance=SimpleNamespace(
                            pk=1,
                            workflow=SimpleNamespace(name="Workflow"),
                        ),
                        workflow_step=SimpleNamespace(name="Step"),
                        submitted_at=None,
                        performed_by="tester",
                    ),
                    snapshot=snapshot,
                )
            ],
            "device": None,
            "legacy_histories": [],
        })

    def test_renders_nested_repeatable_groups_recursively(self):
        grandchild = self._group(
            "Grandchild",
            [self._item([self._field("Grandchild Field", display_value="G")])],
        )
        child = self._group(
            "Child",
            [
                self._item(
                    [self._field("Child Field", display_value="C")],
                    child_groups=[grandchild],
                )
            ],
        )
        parent = self._group(
            "Parent",
            [
                self._item(
                    [self._field("Parent Field", display_value="P")],
                    child_groups=[child],
                )
            ],
        )

        rendered = self._render({
            "fields": [],
            "repeatable_groups": [parent],
        })

        self.assertIn("Parent", rendered)
        self.assertIn("Child", rendered)
        self.assertIn("Grandchild", rendered)
        self.assertIn("P", rendered)
        self.assertIn("C", rendered)
        self.assertIn("G", rendered)

    def test_renders_repeatable_file_snapshot_metadata(self):
        parent = self._group(
            "Attachments",
            [
                self._item(
                    [
                        self._field(
                            "Attachment",
                            file=SimpleNamespace(
                                name="repair.pdf",
                                size=4096,
                                content_type="application/pdf",
                            ),
                        )
                    ]
                )
            ],
        )

        rendered = self._render({
            "fields": [],
            "repeatable_groups": [parent],
        })

        self.assertIn("repair.pdf", rendered)
        self.assertIn("4096 bytes", rendered)
        self.assertIn("application/pdf", rendered)

    def test_renders_zero_and_false_values_instead_of_empty_marker(self):
        group = self._group(
            "Values",
            [
                self._item([
                    self._field("Zero", display_value=0),
                    self._field("False", display_value=False),
                ])
            ],
        )

        rendered = self._render({
            "fields": [],
            "repeatable_groups": [group],
        })

        self.assertIn(">0<", rendered)
        self.assertIn(">False<", rendered)

    @patch("operator_panel.history_views.redirect")
    @patch("operator_panel.history_views.reverse")
    @patch.object(history_views.WorkflowAuthorizationService, "require_permission")
    @patch("operator_panel.history_views.get_object_or_404")
    def test_workflow_history_requires_history_permission_and_redirects_to_read_only_form(
        self,
        get_object_or_404,
        require_permission,
        reverse_url,
        redirect,
    ):
        instance = SimpleNamespace(
            pk=42,
            workflow=SimpleNamespace(name="Workflow"),
            current_step=SimpleNamespace(),
        )
        get_object_or_404.return_value = instance
        reverse_url.return_value = "/operator/workflow-instance/42/"
        redirect.return_value = "response"
        request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True),
        )

        response = history_views.workflow_history.__wrapped__(
            request,
            instance_id=42,
        )

        self.assertEqual(response, "response")
        require_permission.assert_called_once_with(
            user=request.user,
            workflow=instance.workflow,
            action=HISTORY_ACTION,
        )
        reverse_url.assert_called_once_with(
            "operator_panel:workflow_instance",
            args=[42],
        )
        redirect.assert_called_once_with(
            "/operator/workflow-instance/42/?source=history",
        )

    def test_device_history_url_resolves_to_canonical_history_view(self):
        match = resolve(
            reverse(
                "operator_panel:device_history",
                kwargs={"instance_id": 42, "device_id": 7},
            )
        )

        self.assertIs(match.func, history_views.device_history)

    @patch("operator_panel.history_views.redirect")
    @patch("operator_panel.history_views.reverse")
    @patch.object(history_views.WorkflowAuthorizationService, "require_permission")
    @patch("operator_panel.history_views.InstanceDevice.objects.filter")
    @patch("operator_panel.history_views.get_object_or_404")
    def test_device_history_redirects_to_previous_workflow_instance(
        self,
        get_object_or_404,
        filter_devices,
        require_permission,
        reverse_url,
        redirect,
    ):
        instance = SimpleNamespace(
            pk=42,
            workflow=SimpleNamespace(name="Workflow"),
            current_step=SimpleNamespace(),
        )
        device = SimpleNamespace(pk=7)
        get_object_or_404.side_effect = [instance, device]
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))
        reverse_url.return_value = "/operator/workflow-instance/18/"
        redirect.return_value = "response"

        queryset = MagicMock()
        filter_devices.return_value = queryset
        previous_queryset = MagicMock()
        queryset.exclude.return_value = previous_queryset
        previous_queryset.select_related.return_value = previous_queryset
        previous_queryset.order_by.return_value = previous_queryset
        previous_queryset.values_list.return_value.first.return_value = 18

        response = history_views.device_history.__wrapped__(
            request,
            instance_id=42,
            device_id=7,
        )

        self.assertEqual(response, "response")
        require_permission.assert_called_once_with(
            user=request.user,
            workflow=instance.workflow,
            action=HISTORY_ACTION,
        )
        filter_devices.assert_called_once_with(device=device)
        queryset.exclude.assert_called_once_with(instance_id=42)
        previous_queryset.select_related.assert_called_once_with(
            "instance",
            "instance__workflow",
            "instance__current_step",
        )
        previous_queryset.order_by.assert_called_once_with(
            "-instance__started_at",
            "-received_at",
        )
        previous_queryset.values_list.assert_called_once_with("instance", flat=True)
        reverse_url.assert_called_once_with(
            "operator_panel:workflow_instance",
            args=[18],
        )
        redirect.assert_called_once_with(
            "/operator/workflow-instance/18/?source=history_device",
        )

    @patch.object(history_views.WorkflowAuthorizationService, "require_permission")
    @patch("operator_panel.history_views.InstanceDevice.objects.filter")
    @patch("operator_panel.history_views.get_object_or_404")
    def test_device_history_requires_a_previous_instance(
        self,
        get_object_or_404,
        filter_devices,
        require_permission,
    ):
        instance = SimpleNamespace(
            pk=42,
            workflow=SimpleNamespace(name="Workflow"),
            current_step=SimpleNamespace(),
        )
        device = SimpleNamespace(pk=7)
        get_object_or_404.side_effect = [instance, device]
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True))

        queryset = MagicMock()
        filter_devices.return_value = queryset
        previous_queryset = MagicMock()
        queryset.exclude.return_value = previous_queryset
        previous_queryset.select_related.return_value = previous_queryset
        previous_queryset.order_by.return_value = previous_queryset
        previous_queryset.values_list.return_value.first.return_value = None

        with self.assertRaises(PermissionDenied):
            history_views.device_history.__wrapped__(
                request,
                instance_id=42,
                device_id=7,
            )

        require_permission.assert_called_once_with(
            user=request.user,
            workflow=instance.workflow,
            action=HISTORY_ACTION,
        )
        filter_devices.assert_called_once_with(device=device)

    def test_renders_top_level_zero_and_false_values(self):
        rendered = self._render({
            "fields": [
                self._field("Zero", display_value=0),
                self._field("False", display_value=False),
            ],
            "repeatable_groups": [],
        })

        self.assertIn(">0<", rendered)
        self.assertIn(">False<", rendered)
