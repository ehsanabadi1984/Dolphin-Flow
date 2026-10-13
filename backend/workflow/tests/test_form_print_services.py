from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase

from workflow.form_print_services import FormPrintDataService


class FormPrintDataServiceTests(SimpleTestCase):
    def setUp(self):
        self.step = SimpleNamespace(pk=7)
        self.workflow = SimpleNamespace(name="Repair", is_active=True)
        self.instance = SimpleNamespace(
            pk=123,
            workflow=self.workflow,
            current_step=self.step,
            started_at=None,
        )
        self.form = SimpleNamespace(name="Repair form")
        self.section = SimpleNamespace(
            pk=1,
            name="Visible section",
            order=1,
        )
        self.visible_field = SimpleNamespace(
            pk=10,
            label="Visible field",
            order=1,
        )
        self.dynamic_form = {
            "form": self.form,
            "sections": [
                {
                    "section": self.section,
                    "fields": [
                        {
                            "field": self.visible_field,
                            "value": "visible-value",
                            "display_value": "visible-value",
                        }
                    ],
                    "repeatable_groups": [],
                }
            ],
        }

    def _prepare(self, *, field_settings=None, section_settings=None):
        with (
            patch(
                "workflow.form_print_services.WorkflowAuthorizationService.has_permission",
                return_value=True,
            ),
            patch(
                "workflow.form_print_services.DynamicFormService.get_form_for_step",
                return_value=self.dynamic_form,
            ),
            patch(
                "workflow.form_print_services.FormPrintSettings.objects.filter",
                return_value=SimpleNamespace(first=lambda: None),
            ),
            patch(
                "workflow.form_print_services.FormPrintSectionSettings.objects.filter",
                return_value=section_settings or [],
            ),
            patch(
                "workflow.form_print_services.FormPrintFieldSettings.objects.filter",
                return_value=field_settings or [],
            ),
        ):
            return FormPrintDataService.prepare(
                instance=self.instance,
                user=SimpleNamespace(pk=99, is_authenticated=True, is_active=True),
            )

    def test_only_fields_in_permission_filtered_form_context_are_copied(self):
        # DynamicFormService omits unauthorized fields. The print service must
        # not independently re-read FormData and accidentally reintroduce them.
        result = self._prepare()

        rendered_text = repr(result)
        self.assertIn("visible-value", rendered_text)
        self.assertNotIn("secret-value", rendered_text)
        self.assertEqual(
            result["sections"][0]["items"][0]["label"],
            "Visible field",
        )

    def test_disabled_print_field_is_omitted(self):
        print_setting = SimpleNamespace(
            field_id=self.visible_field.pk,
            repeatable_group_id=None,
            is_enabled=False,
            title_override="",
            print_order=0,
            group_layout="TABLE",
        )

        result = self._prepare(field_settings=[print_setting])

        self.assertEqual(result["sections"], [])

    def test_disabled_field_inside_repeatable_group_is_omitted(self):
        group = SimpleNamespace(pk=20, label="Devices", name="Devices", order=1)
        repeatable_field = SimpleNamespace(pk=31, label="Serial number")
        field_setting = SimpleNamespace(
            field_id=repeatable_field.pk,
            repeatable_group_id=None,
            is_enabled=False,
            title_override="",
            print_order=0,
            group_layout="TABLE",
        )
        group_context = {
            "group": group,
            "fields": [{"field": repeatable_field, "value": "", "display_value": ""}],
            "items": [
                {
                    "fields": [
                        {
                            "field": repeatable_field,
                            "value": "SN-123",
                            "display_value": "SN-123",
                        }
                    ],
                    "child_groups": [],
                }
            ],
        }

        result = FormPrintDataService._group_item(
            group_context,
            setting=None,
            field_settings={(repeatable_field.pk, None): field_setting},
            show_empty_values=False,
        )

        self.assertIsNone(result)

    def test_denied_workflow_view_permission_stops_before_form_data_is_built(self):
        with (
            patch(
                "workflow.form_print_services.WorkflowAuthorizationService.has_permission",
                return_value=False,
            ),
            patch(
                "workflow.form_print_services.DynamicFormService.get_form_for_step",
            ) as build_form,
        ):
            with self.assertRaises(PermissionDenied):
                FormPrintDataService.prepare(
                    instance=self.instance,
                    user=SimpleNamespace(
                        pk=99,
                        is_authenticated=True,
                        is_active=True,
                    ),
                )

        build_form.assert_not_called()

    def test_disabled_print_section_is_omitted(self):
        print_setting = SimpleNamespace(
            section_id=self.section.pk,
            is_enabled=False,
            title_override="",
            print_order=0,
        )

        result = self._prepare(section_settings=[print_setting])

        self.assertEqual(result["sections"], [])
