from pathlib import Path
import re

path = Path(__file__).with_name("test_dynamic_form_service.py")
text = path.read_text(encoding="utf-8")

# Add persistent-device helper once.
needle = '''        return instance\n\n    def test_get_form_for_step_returns_repeatable_device_group(self):'''
replacement = '''        return instance\n\n    def create_persistent_device(self, imei, device_model=None):\n        device = Device.objects.create(\n            device_model=device_model or self.device_model,\n        )\n        DeviceIdentifier.objects.create(\n            device=device,\n            identifier_type=DeviceIdentifier.IdentifierType.IMEI,\n            value=imei,\n        )\n        return device\n\n    def test_get_form_for_step_returns_repeatable_device_group(self):'''
if needle not in text:
    raise SystemExit("helper insertion point not found")
text = text.replace(needle, replacement, 1)

# Tests which inspect a persistent Device must seed one first.
persistent_tests = {
    "test_save_form_creates_device_from_repeatable_group": "777777777777777",
    "test_save_form_creates_multiple_devices": None,
    "test_deactivate_instance_device": "333333333333333",
    "test_get_form_for_step_hides_deactivated_device": "999999999999999",
    "test_save_form_rejects_device_field_without_edit_access": "555555555555555",
    "test_save_form_updates_existing_device_from_form": "666666666666666",
    "test_save_form_updates_existing_device_imei_when_editable": "333333333333333",
    "test_save_form_rejects_imei_belonging_to_another_device": None,
    "test_clear_form_does_not_delete_persistent_devices": "123123123123123",
}

for test_name, imei in persistent_tests.items():
    pattern = rf'(    def {test_name}\(.*?\):\n        instance = self\.create_instance\(\)\n)'
    match = re.search(pattern, text, re.S)
    if not match:
        continue
    if test_name == "test_save_form_creates_multiple_devices":
        insert = '''\n        self.create_persistent_device(\n            imei="111111111111111",\n            device_model=self.device_model,\n        )\n        second_device_model = DeviceModel.objects.create(\n'''
        old = '''\n        second_device_model = DeviceModel.objects.create(\n'''
        text = text[:match.end()] + old + text[match.end():]
        # Add the second persistent device after second model is created below.
        marker = '''            code="TEST_MODEL_2",\n            is_active=True,\n        )\n\n        submitted_data = {'''
        if marker in text:
            text = text.replace(marker, '''            code="TEST_MODEL_2",\n            is_active=True,\n        )\n\n        self.create_persistent_device(\n            imei="222222222222222",\n            device_model=second_device_model,\n        )\n\n        submitted_data = {''', 1)
    elif test_name == "test_save_form_rejects_imei_belonging_to_another_device":
        insert = '''\n        self.create_persistent_device(\n            imei="111111111111111",\n            device_model=self.device_model,\n        )\n        self.create_persistent_device(\n            imei="222222222222222",\n            device_model=self.device_model,\n        )\n'''
        text = text[:match.end()] + insert + text[match.end():]
    else:
        insert = f'''\n        self.create_persistent_device(\n            imei="{imei}",\n            device_model=self.device_model,\n        )\n'''
        text = text[:match.end()] + insert + text[match.end():]

# Existing-row updates must carry the InstanceDevice identity.
updates = [
    ("test_save_form_updates_existing_instance_device", '"reported_problem": "مشکل به‌روزشده"'),
    ("test_save_form_updates_existing_device_from_form", '"reported_problem": "مشکل به‌روزشده"'),
    ("test_device_group_view_only_cannot_be_edited", '"reported_problem": "تلاش برای ویرایش غیرمجاز"'),
]
for test_name, marker in updates:
    start = text.find(f"    def {test_name}(")
    if start < 0:
        continue
    end = text.find("\n    def ", start + 10)
    block_end = len(text) if end < 0 else end
    block = text[start:block_end]
    if '"instance_device_id":' in block:
        continue
    # Insert identity immediately before the IMEI in the update submission row.
    block = block.replace('''                {\n                    "imei":''', '''                {\n                    "instance_device_id": instance_device.pk,\n                    "imei":''', 1)
    text = text[:start] + block + text[block_end:]

# The two-device update test must submit both existing rows.
start = text.find("    def test_save_form_updates_one_device_without_affecting_other_devices(")
if start >= 0:
    end = text.find("\n    def ", start + 10)
    block_end = len(text) if end < 0 else end
    block = text[start:block_end]
    old = '''                {\n                    "imei": "777777777777777",\n                    "device_model_id": self.device_model.pk,\n                    "reported_problem": "مشکل دستگاه اول - UPDATED",\n                    "warranty_status": "WARRANTY",\n                    "status": "IN_REPAIR",\n                },\n            ],'''
    new = '''                {\n                    "instance_device_id": first_id,\n                    "imei": "777777777777777",\n                    "device_model_id": self.device_model.pk,\n                    "reported_problem": "مشکل دستگاه اول - UPDATED",\n                    "warranty_status": "WARRANTY",\n                    "status": "IN_REPAIR",\n                },\n                {\n                    "instance_device_id": second_id,\n                    "imei": "888888888888888",\n                    "device_model_id": self.device_model.pk,\n                    "reported_problem": "مشکل دستگاه دوم",\n                    "warranty_status": "UNKNOWN",\n                    "status": "RECEIVED",\n                },\n            ],'''
    if old in block:
        block = block.replace(old, new, 1)
        text = text[:start] + block + text[block_end:]

# clear_form is an edit operation.
text = text.replace('''        DynamicFormService.clear_form_for_step(\n            instance=instance,\n            user=self.user,\n        )''', '''        DynamicFormService.clear_form_for_step(\n            instance=instance,\n            user=self.user,\n            edit_mode=True,\n        )''')

# Persistent-device IMEI is immutable in production. Replace the old editable-IMEI expectation.
start = text.find("    def test_save_form_updates_existing_device_imei_when_editable(")
if start >= 0:
    end = text.find("\n    def ", start + 10)
    block_end = len(text) if end < 0 else end
    block = text[start:block_end]
    call = '''        DynamicFormService.save_form_for_step(\n            instance=instance,\n            user=self.user,\n            submitted_data=self.flatten_repeatable_submission(second_submission),\n            edit_mode=True,\n        )'''
    if call in block:
        block = block.replace(call, '''        with self.assertRaises(ValidationError):\n            DynamicFormService.save_form_for_step(\n                instance=instance,\n                user=self.user,\n                submitted_data=self.flatten_repeatable_submission(second_submission),\n                edit_mode=True,\n            )''', 1)
    old_asserts = '''        self.assertTrue(\n            DeviceIdentifier.objects.filter(\n                device=instance_device.device,\n                identifier_type="IMEI",\n                value="444444444444444",\n            ).exists()\n        )\n\n        self.assertFalse(\n            DeviceIdentifier.objects.filter(\n                device=instance_device.device,\n                identifier_type="IMEI",\n                value="333333333333333",\n            ).exists()\n        )'''
    new_asserts = '''        self.assertTrue(\n            DeviceIdentifier.objects.filter(\n                device=instance_device.device,\n                identifier_type="IMEI",\n                value="333333333333333",\n            ).exists()\n        )\n\n        self.assertFalse(\n            DeviceIdentifier.objects.filter(\n                device=instance_device.device,\n                identifier_type="IMEI",\n                value="444444444444444",\n            ).exists()\n        )'''
    block = block.replace(old_asserts, new_asserts, 1)
    text = text[:start] + block + text[block_end:]

# Write only if the transformation really happened.
path.write_text(text, encoding="utf-8")
print(f"updated {path}")
