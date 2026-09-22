from datetime import date, datetime
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.form_draft_payloads import NormalizedFormPayload, NormalizedRow
from workflow.form_draft_value_validation_services import (
    FormDraftValueValidationService,
)
from workflow.models import (
    DeviceModel,
    DeviceType,
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    FormData,
    LookupItem,
    LookupList,
    RepeatableRow,
    RepeatableRowValue,
    StaticChoiceItem,
    StaticChoiceSet,
    Workflow,
    WorkflowInstance,
)


class FormDraftValueValidationServiceTests(TestCase):
    def setUp(self):
        self.workflow = Workflow.objects.create(
            name="Value Validation Workflow",
            code="VALUE_VALIDATION_WF",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="Value Validation Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Section",
            code="SECTION",
            order=1,
        )
        self.instance = WorkflowInstance.objects.create(
            workflow=self.workflow,
        )

    def field(
        self,
        *,
        code,
        field_type=FormField.FieldType.TEXT,
        group=None,
        **kwargs,
    ):
        existing_fields = FormField.objects.filter(
            section=self.section,
            repeatable_group=group,
        ).count()
        return FormField.objects.create(
            section=self.section,
            repeatable_group=group,
            name=code.title(),
            code=code,
            label=code.title(),
            field_type=field_type,
            order=existing_fields + 1,
            **kwargs,
        )

    def payload(self, *, normal_fields=None, groups=None):
        return NormalizedFormPayload(
            normal_fields=normal_fields or {},
            repeatable_groups=groups or {},
        )

    def validate(self, payload):
        return FormDraftValueValidationService.validate_payload(
            instance=self.instance,
            form=self.form,
            normalized_payload=payload,
        )

    def test_accepts_empty_values_for_draft(self):
        fields = [
            self.field(code="text", field_type=FormField.FieldType.TEXT),
            self.field(code="number", field_type=FormField.FieldType.NUMBER),
            self.field(code="date", field_type=FormField.FieldType.DATE),
            self.field(code="datetime", field_type=FormField.FieldType.DATETIME),
            self.field(code="boolean", field_type=FormField.FieldType.BOOLEAN),
        ]

        self.validate(
            self.payload(
                normal_fields={field.code: "" for field in fields},
            )
        )

    def test_validates_normal_field_value_families(self):
        self.field(code="text", field_type=FormField.FieldType.TEXT)
        self.field(code="number", field_type=FormField.FieldType.NUMBER)
        self.field(code="date", field_type=FormField.FieldType.DATE)
        self.field(code="datetime", field_type=FormField.FieldType.DATETIME)
        self.field(code="boolean", field_type=FormField.FieldType.BOOLEAN)

        self.validate(
            self.payload(
                normal_fields={
                    "text": "hello",
                    "number": "12.50",
                    "date": "2026-09-21",
                    "datetime": "2026-09-21T10:30:00+03:30",
                    "boolean": "true",
                }
            )
        )

    def test_rejects_malformed_number(self):
        self.field(code="number", field_type=FormField.FieldType.NUMBER)

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"number": "abc"}))

    def test_rejects_malformed_date(self):
        self.field(code="date", field_type=FormField.FieldType.DATE)

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"date": "21/09/2026"}))

    def test_rejects_malformed_datetime(self):
        self.field(code="datetime", field_type=FormField.FieldType.DATETIME)

        with self.assertRaises(ValidationError):
            self.validate(
                self.payload(
                    normal_fields={"datetime": "not-a-datetime"},
                )
            )

    def test_rejects_invalid_boolean(self):
        self.field(code="boolean", field_type=FormField.FieldType.BOOLEAN)

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"boolean": "maybe"}))

    def test_rejects_non_text_value_for_text_field(self):
        self.field(code="text", field_type=FormField.FieldType.TEXT)

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"text": ["bad"]}))

    def test_validates_static_select(self):
        choice_set = StaticChoiceSet.objects.create(
            name="Status",
            code="STATUS",
        )
        item = StaticChoiceItem.objects.create(
            choice_set=choice_set,
            value="OPEN",
            label="Open",
        )
        self.field(
            code="status",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.STATIC,
            choice_static_set=choice_set,
        )

        self.validate(self.payload(normal_fields={"status": item.value}))

    def test_rejects_invalid_static_select(self):
        choice_set = StaticChoiceSet.objects.create(
            name="Status",
            code="STATUS",
        )
        StaticChoiceItem.objects.create(
            choice_set=choice_set,
            value="OPEN",
            label="Open",
        )
        self.field(
            code="status",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.STATIC,
            choice_static_set=choice_set,
        )

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"status": "CLOSED"}))

    def test_rejects_inactive_static_select(self):
        choice_set = StaticChoiceSet.objects.create(
            name="Status",
            code="STATUS",
        )
        item = StaticChoiceItem.objects.create(
            choice_set=choice_set,
            value="OPEN",
            label="Open",
            is_active=False,
        )
        self.field(
            code="status",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.STATIC,
            choice_static_set=choice_set,
        )

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"status": item.value}))

    def test_validates_lookup_select(self):
        lookup = LookupList.objects.create(
            name="Priority",
            code="PRIORITY",
        )
        item = LookupItem.objects.create(
            lookup_list=lookup,
            value="HIGH",
            label="High",
        )
        self.field(
            code="priority",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
        )

        self.validate(self.payload(normal_fields={"priority": item.value}))

    def test_rejects_invalid_lookup_select(self):
        lookup = LookupList.objects.create(
            name="Priority",
            code="PRIORITY",
        )
        LookupItem.objects.create(
            lookup_list=lookup,
            value="HIGH",
            label="High",
        )
        self.field(
            code="priority",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
        )

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"priority": "LOW"}))

    def test_validates_model_select_reference(self):
        device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE",
        )
        device_model = DeviceModel.objects.create(
            device_type=device_type,
            brand="Acme",
            name="X1",
            code="X1",
        )
        content_type = ContentType.objects.get_for_model(DeviceModel)
        self.field(
            code="model",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=content_type,
            choice_label_field="name",
            choice_value_field="id",
        )

        self.validate(
            self.payload(normal_fields={"model": str(device_model.pk)})
        )

    def test_rejects_missing_model_select_reference(self):
        device_type = DeviceType.objects.create(
            name="Phone",
            code="PHONE",
        )
        DeviceModel.objects.create(
            device_type=device_type,
            brand="Acme",
            name="X1",
            code="X1",
        )
        content_type = ContentType.objects.get_for_model(DeviceModel)
        self.field(
            code="model",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=content_type,
            choice_label_field="name",
            choice_value_field="id",
        )

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"model": "999999"}))

    def test_rejects_model_select_with_invalid_value_field_definition(self):
        content_type = ContentType.objects.get_for_model(DeviceModel)
        self.field(
            code="model",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.MODEL,
            choice_model=content_type,
            choice_label_field="name",
            choice_value_field="missing_field",
        )

        with self.assertRaises(ValidationError):
            self.validate(self.payload(normal_fields={"model": "1"}))

    def test_validates_repeatable_values(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )
        self.field(
            code="amount",
            field_type=FormField.FieldType.NUMBER,
            group=group,
        )
        row = NormalizedRow(
            row_id=None,
            fields={"amount": "12.5"},
            child_groups={},
        )

        self.validate(
            self.payload(
                groups={"items": (row,)},
            )
        )

    def test_rejects_invalid_repeatable_value(self):
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )
        self.field(
            code="amount",
            field_type=FormField.FieldType.NUMBER,
            group=group,
        )
        row = NormalizedRow(
            row_id=None,
            fields={"amount": "broken"},
            child_groups={},
        )

        with self.assertRaises(ValidationError):
            self.validate(self.payload(groups={"items": (row,)}))

    def test_dependent_lookup_rejects_child_when_parent_is_empty(self):
        lookup = LookupList.objects.create(
            name="Regions",
            code="REGIONS",
        )
        parent = LookupItem.objects.create(
            lookup_list=lookup,
            value="TEHRAN",
            label="Tehran",
        )
        child = LookupItem.objects.create(
            lookup_list=lookup,
            parent=parent,
            value="NORTH",
            label="North",
        )
        parent_field = self.field(
            code="region",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
        )
        self.field(
            code="area",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
            choice_parent_field=parent_field,
        )

        with self.assertRaises(ValidationError):
            self.validate(
                self.payload(
                    normal_fields={"region": "", "area": child.value},
                )
            )

    def test_dependent_lookup_accepts_matching_child(self):
        lookup = LookupList.objects.create(
            name="Regions",
            code="REGIONS",
        )
        parent = LookupItem.objects.create(
            lookup_list=lookup,
            value="TEHRAN",
            label="Tehran",
        )
        child = LookupItem.objects.create(
            lookup_list=lookup,
            parent=parent,
            value="NORTH",
            label="North",
        )
        parent_field = self.field(
            code="region",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
        )
        self.field(
            code="area",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
            choice_parent_field=parent_field,
        )

        self.validate(
            self.payload(
                normal_fields={"region": parent.value, "area": child.value},
            )
        )

    def test_dependent_lookup_rejects_child_from_another_parent(self):
        lookup = LookupList.objects.create(
            name="Regions",
            code="REGIONS",
        )
        parent_a = LookupItem.objects.create(
            lookup_list=lookup,
            value="TEHRAN",
            label="Tehran",
        )
        parent_b = LookupItem.objects.create(
            lookup_list=lookup,
            value="TABRIZ",
            label="Tabriz",
        )
        child = LookupItem.objects.create(
            lookup_list=lookup,
            parent=parent_b,
            value="NORTH",
            label="North",
        )
        parent_field = self.field(
            code="region",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
        )
        self.field(
            code="area",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
            choice_parent_field=parent_field,
        )

        with self.assertRaises(ValidationError):
            self.validate(
                self.payload(
                    normal_fields={"region": parent_a.value, "area": child.value},
                )
            )

    def test_repeatable_dependency_uses_canonical_persisted_parent_when_omitted(self):
        lookup = LookupList.objects.create(
            name="Regions",
            code="REGIONS",
        )
        parent = LookupItem.objects.create(
            lookup_list=lookup,
            value="TEHRAN",
            label="Tehran",
        )
        child = LookupItem.objects.create(
            lookup_list=lookup,
            parent=parent,
            value="NORTH",
            label="North",
        )
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )
        parent_field = self.field(
            code="region",
            field_type=FormField.FieldType.SELECT,
            group=group,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
        )
        child_field = self.field(
            code="area",
            field_type=FormField.FieldType.SELECT,
            group=group,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
            choice_parent_field=parent_field,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=parent_field,
            lookup_item=parent,
        )

        self.validate(
            self.payload(
                groups={
                    "items": (
                        NormalizedRow(
                            row_id=row.pk,
                            fields={"area": child.value},
                            child_groups={},
                        ),
                    )
                }
            )
        )

    def test_repeatable_dependency_rejects_submitted_child_against_persisted_parent(self):
        lookup = LookupList.objects.create(
            name="Regions",
            code="REGIONS",
        )
        parent = LookupItem.objects.create(
            lookup_list=lookup,
            value="TEHRAN",
            label="Tehran",
        )
        other_parent = LookupItem.objects.create(
            lookup_list=lookup,
            value="TABRIZ",
            label="Tabriz",
        )
        child = LookupItem.objects.create(
            lookup_list=lookup,
            parent=other_parent,
            value="NORTH",
            label="North",
        )
        group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Items",
            code="items",
            order=1,
        )
        parent_field = self.field(
            code="region",
            field_type=FormField.FieldType.SELECT,
            group=group,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
        )
        child_field = self.field(
            code="area",
            field_type=FormField.FieldType.SELECT,
            group=group,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
            choice_parent_field=parent_field,
        )
        row = RepeatableRow.objects.create(
            instance=self.instance,
            group=group,
            row_order=0,
        )
        RepeatableRowValue.objects.create(
            row=row,
            field=parent_field,
            lookup_item=parent,
        )

        with self.assertRaises(ValidationError):
            self.validate(
                self.payload(
                    groups={
                        "items": (
                            NormalizedRow(
                                row_id=row.pk,
                                fields={"area": child.value},
                                child_groups={},
                            ),
                        )
                    }
                )
            )

    def test_blank_dependent_child_is_accepted(self):
        lookup = LookupList.objects.create(
            name="Regions",
            code="REGIONS",
        )
        parent = LookupItem.objects.create(
            lookup_list=lookup,
            value="TEHRAN",
            label="Tehran",
        )
        parent_field = self.field(
            code="region",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
        )
        self.field(
            code="area",
            field_type=FormField.FieldType.SELECT,
            choice_source=FormField.ChoiceSource.LOOKUP,
            choice_lookup_list=lookup,
            choice_parent_field=parent_field,
        )

        self.validate(
            self.payload(
                normal_fields={"region": parent.value, "area": ""},
            )
        )
