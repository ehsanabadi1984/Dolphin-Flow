from types import SimpleNamespace
from unittest.mock import patch

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

    def test_disabled_print_section_is_omitted(self):
        print_setting = SimpleNamespace(
            section_id=self.section.pk,
            is_enabled=False,
            title_override="",
            print_order=0,
        )

        result = self._prepare(section_settings=[print_setting])

        self.assertEqual(result["sections"], [])
