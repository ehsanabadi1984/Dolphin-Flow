from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from accounts.models import User
from workflow.admin import RepeatableFieldInline
from workflow.file_share_authorization import (
    can_share_file_field,
    has_direct_share_files_permission,
    require_file_share_permission,
)
from workflow.form_workspace import FormFieldWorkspaceForm
from workflow.models import (
    FormDefinition,
    FormField,
    FormRepeatableGroup,
    FormSection,
    Workflow,
)


class FileShareAuthorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="file-share-user",
            password="test-password",
        )
        self.permission = Permission.objects.get(
            content_type__app_label="accounts",
            content_type__model="user",
            codename="share_files",
        )
        self.workflow = Workflow.objects.create(
            name="File Sharing Workflow",
            code="FILE_SHARING",
        )
        self.form = FormDefinition.objects.create(
            workflow=self.workflow,
            name="File Sharing Form",
        )
        self.section = FormSection.objects.create(
            form=self.form,
            name="Attachments",
            code="ATTACHMENTS",
            order=1,
        )
        self.repeatable_group = FormRepeatableGroup.objects.create(
            section=self.section,
            name="Documents",
            code="DOCUMENTS",
            order=1,
        )

    def make_field(self, *, field_type=FormField.FieldType.FILE,
                   allow_file_sharing=True, repeatable=False):
        suffix = FormField.objects.count() + 1
        return FormField.objects.create(
            section=self.section,
            repeatable_group=self.repeatable_group if repeatable else None,
            name=f"file_share_field_{suffix}",
            code=f"file_share_field_{suffix}",
            label="Attachment",
            field_type=field_type,
            allow_file_sharing=allow_file_sharing,
        )

    def test_user_with_direct_permission_is_authorized(self):
        self.user.user_permissions.add(self.permission)
        self.assertTrue(has_direct_share_files_permission(self.user))

    def test_user_without_permission_is_not_authorized(self):
        self.assertFalse(has_direct_share_files_permission(self.user))

    def test_group_permission_does_not_grant_file_sharing(self):
        group = Group.objects.create(name="File sharers")
        group.permissions.add(self.permission)
        self.user.groups.add(group)

        self.assertTrue(self.user.has_perm("accounts.share_files"))
        self.assertFalse(has_direct_share_files_permission(self.user))

    def test_superuser_is_authorized_without_direct_assignment(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        self.assertTrue(has_direct_share_files_permission(self.user))

    def test_file_field_requires_both_permission_and_field_switch(self):
        self.user.user_permissions.add(self.permission)
        enabled_field = self.make_field()
        disabled_field = self.make_field(
            field_type=FormField.FieldType.FILE,
            allow_file_sharing=False,
        )

        self.assertTrue(can_share_file_field(user=self.user, field=enabled_field))
        self.assertFalse(can_share_file_field(user=self.user, field=disabled_field))

    def test_non_file_field_cannot_be_shared_even_if_flag_is_set(self):
        self.user.user_permissions.add(self.permission)
        field = self.make_field(
            field_type=FormField.FieldType.TEXT,
            allow_file_sharing=False,
        )
        field.allow_file_sharing = True
        field.clean()

        self.assertFalse(field.allow_file_sharing)
        self.assertFalse(can_share_file_field(user=self.user, field=field))

    def test_repeatable_file_field_can_be_shared(self):
        self.user.user_permissions.add(self.permission)
        field = self.make_field(repeatable=True)

        self.assertEqual(field.repeatable_group_id, self.repeatable_group.pk)
        self.assertTrue(can_share_file_field(user=self.user, field=field))

    def test_permission_is_required_by_guard(self):
        field = self.make_field()
        with self.assertRaises(PermissionDenied):
            require_file_share_permission(user=self.user, field=field)

    def test_workspace_hides_and_disables_option_for_non_file_fields(self):
        text_field = self.make_field(
            field_type=FormField.FieldType.TEXT,
            allow_file_sharing=False,
        )
        form = FormFieldWorkspaceForm(instance=text_field, form_definition=self.form)

        self.assertIn("allow_file_sharing", form.fields)
        self.assertTrue(form.fields["allow_file_sharing"].disabled)
        self.assertFalse(form.fields["allow_file_sharing"].initial)

    def test_workspace_enables_option_for_file_fields(self):
        file_field = self.make_field()
        form = FormFieldWorkspaceForm(instance=file_field, form_definition=self.form)

        self.assertFalse(form.fields["allow_file_sharing"].disabled)

    def test_repeatable_inline_exposes_file_sharing_option(self):
        self.assertIn("allow_file_sharing", RepeatableFieldInline.fields)
