from types import SimpleNamespace

from django.template.loader import get_template
from django.test import SimpleTestCase


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
        return template.render({
            "history_title": "سوابق",
            "history_subtitle": "Workflow",
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
