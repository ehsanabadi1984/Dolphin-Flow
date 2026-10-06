from dataclasses import dataclass
from typing import FrozenSet

from .models import FieldAccess, FormRepeatableGroup, RepeatableGroupAccess


@dataclass(frozen=True)
class FieldPermission:
    can_view: bool
    can_edit: bool


@dataclass(frozen=True)
class GroupPermission:
    can_view: bool
    can_edit: bool
    can_add: bool
    can_delete: bool


class PermissionContext:
    """
    Immutable permission snapshot for one form/step/user combination.

    Permission precedence intentionally mirrors the existing form behavior:
    a matching user rule wins over all role rules; when no user rule exists,
    role rules are evaluated across the user's active workflow roles.
    """

    def __init__(
        self,
        *,
        roles: FrozenSet[str],
        normal_fields: dict[int, FieldPermission],
        repeatable_fields: dict[int, FieldPermission],
        groups: dict[int, GroupPermission],
        configured_fields: FrozenSet[int] = frozenset(),
        configured_groups: FrozenSet[int] = frozenset(),
    ):
        self.roles = roles
        self.normal_fields = normal_fields
        self.repeatable_fields = repeatable_fields
        self.groups = groups
        self.configured_fields = configured_fields
        self.configured_groups = configured_groups

    @classmethod
    def build(
        cls,
        *,
        workflow,
        form,
        step,
        user,
    ):
        roles = frozenset(
            workflow.memberships.filter(
                user=user,
                is_active=True,
            ).values_list(
                "role",
                flat=True,
            )
        )

        normal_fields = {}
        repeatable_fields = {}
        groups = {}
        configured_fields = set()
        configured_groups = set()

        sections = form.sections.filter(
            is_active=True,
        ).prefetch_related(
            "fields__access_rules",
            "repeatable_groups__access_rules",
            "repeatable_groups__fields__access_rules",
        )

        for section in sections:
            for field in section.fields.all():
                if not field.is_active:
                    continue

                permission = cls._field_permission(
                    field=field,
                    step=step,
                    user=user,
                    roles=roles,
                )

                if any(rule.step_id == step.pk for rule in field.access_rules.all()):
                    configured_fields.add(field.pk)

                if field.repeatable_group_id is None:
                    normal_fields[field.pk] = permission
                else:
                    repeatable_fields[field.pk] = permission

            for group in section.repeatable_groups.all():
                if not group.is_active:
                    continue

                groups[group.pk] = cls._group_permission(
                    group=group,
                    step=step,
                    user=user,
                    roles=roles,
                )
                if any(rule.step_id == step.pk for rule in group.access_rules.all()):
                    configured_groups.add(group.pk)

        return cls(
            roles=roles,
            normal_fields=normal_fields,
            repeatable_fields=repeatable_fields,
            groups=groups,
            configured_fields=frozenset(configured_fields),
            configured_groups=frozenset(configured_groups),
        )

    @classmethod
    def build_batch(cls, *, scopes):
        """
        Build permission snapshots for multiple form/step/user scopes while
        batching memberships and access-rule reads.
        """
        scopes = list(scopes)
        if not scopes:
            return {}

        workflow_ids = {scope["workflow"].pk for scope in scopes}
        form_ids = {scope["form"].pk for scope in scopes}
        step_ids = {scope["step"].pk for scope in scopes}
        user_ids = {scope["user"].pk for scope in scopes}

        if len(user_ids) != 1:
            raise ValueError("Batch PermissionContext requires one user.")

        user_id = next(iter(user_ids))

        from .models import WorkflowMembership

        roles_by_workflow = {
            workflow_id: frozenset(
                membership["role"]
                for membership in memberships
            )
            for workflow_id, memberships in _group_queryset(
                WorkflowMembership.objects.filter(
                    workflow_id__in=workflow_ids,
                    user_id=user_id,
                    is_active=True,
                ).values("workflow_id", "role"),
                "workflow_id",
            ).items()
        }

        forms = {scope["form"].pk: scope["form"] for scope in scopes}
        section_ids_by_form = {}
        field_ids = set()
        group_ids = set()
        for form in forms.values():
            section_ids = [
                section.pk
                for section in form.sections.all()
                if section.is_active
            ]
            section_ids_by_form[form.pk] = section_ids
            for section in form.sections.all():
                if not section.is_active:
                    continue
                field_ids.update(
                    field.pk
                    for field in section.fields.all()
                    if field.is_active
                )

        groups = list(
            FormRepeatableGroup.objects.filter(
                section_id__in=[
                    section_id
                    for ids in section_ids_by_form.values()
                    for section_id in ids
                ],
                is_active=True,
            )
        )
        group_ids.update(group.pk for group in groups)

        field_rules = _group_rules(
            FieldAccess.objects.filter(
                field_id__in=field_ids,
                step_id__in=step_ids,
            ),
            "field_id",
        )
        group_rules = _group_rules(
            RepeatableGroupAccess.objects.filter(
                group_id__in=group_ids,
                step_id__in=step_ids,
            ),
            "group_id",
        )

        result = {}
        for scope in scopes:
            workflow = scope["workflow"]
            form = scope["form"]
            step = scope["step"]
            user = scope["user"]
            roles = roles_by_workflow.get(workflow.pk, frozenset())

            normal_fields = {}
            repeatable_fields = {}
            groups_permissions = {}
            configured_fields = set()
            configured_groups = set()

            for section in form.sections.all():
                if not section.is_active:
                    continue

                for field in section.fields.all():
                    if not field.is_active:
                        continue
                    rules = [
                        rule for rule in field_rules.get(field.pk, [])
                        if rule.step_id == step.pk
                    ]
                    permission = cls._field_permission_from_rules(
                        rules=rules,
                        user=user,
                        roles=roles,
                    )
                    if rules:
                        configured_fields.add(field.pk)

                    if field.repeatable_group_id is None:
                        normal_fields[field.pk] = permission
                    else:
                        repeatable_fields[field.pk] = permission

            for group in groups:
                if group.section_id not in section_ids_by_form.get(form.pk, []):
                    continue
                rules = [
                    rule for rule in group_rules.get(group.pk, [])
                    if rule.step_id == step.pk
                ]
                groups_permissions[group.pk] = cls._group_permission_from_rules(
                    rules=rules,
                    user=user,
                    roles=roles,
                )
                if rules:
                    configured_groups.add(group.pk)

            key = (workflow.pk, form.pk, step.pk, user.pk)
            result[key] = cls(
                roles=roles,
                normal_fields=normal_fields,
                repeatable_fields=repeatable_fields,
                groups=groups_permissions,
                configured_fields=frozenset(configured_fields),
                configured_groups=frozenset(configured_groups),
            )

        return result

    @staticmethod
    def _field_permission_from_rules(*, rules, user, roles):
        user_rule = next(
            (rule for rule in rules if rule.user_id == user.pk),
            None,
        )
        if user_rule is not None:
            return FieldPermission(
                can_view=user_rule.can_view,
                can_edit=user_rule.can_edit,
            )

        role_rules = [
            rule
            for rule in rules
            if rule.user_id is None and rule.role in roles
        ]
        return FieldPermission(
            can_view=any(rule.can_view for rule in role_rules),
            can_edit=any(rule.can_edit for rule in role_rules),
        )

    @staticmethod
    def _field_permission(*, field, step, user, roles):
        return PermissionContext._field_permission_from_rules(
            rules=[
                rule
                for rule in field.access_rules.all()
                if rule.step_id == step.pk
            ],
            user=user,
            roles=roles,
        )

    @staticmethod
    def _group_permission_from_rules(*, rules, user, roles):
        user_rule = next(
            (rule for rule in rules if rule.user_id == user.pk),
            None,
        )
        if user_rule is not None:
            return GroupPermission(
                can_view=user_rule.can_view,
                can_edit=user_rule.can_edit,
                can_add=user_rule.can_add,
                can_delete=user_rule.can_delete,
            )

        role_rules = [
            rule
            for rule in rules
            if rule.user_id is None and rule.role in roles
        ]
        return GroupPermission(
            can_view=any(rule.can_view for rule in role_rules),
            can_edit=any(rule.can_edit for rule in role_rules),
            can_add=any(rule.can_add for rule in role_rules),
            can_delete=any(rule.can_delete for rule in role_rules),
        )

    @staticmethod
    def _group_permission(*, group, step, user, roles):
        return PermissionContext._group_permission_from_rules(
            rules=[
                rule
                for rule in group.access_rules.all()
                if rule.step_id == step.pk
            ],
            user=user,
            roles=roles,
        )

    def field(self, field):
        if field.repeatable_group_id is None:
            return self.normal_fields.get(
                field.pk,
                FieldPermission(False, False),
            )

        return self.repeatable_fields.get(
            field.pk,
            FieldPermission(False, False),
        )

    def is_field_hidden(self, field):
        return (
            field.pk in self.configured_fields
            and not self.field(field).can_view
        )

    def group(self, group):
        return self.groups.get(
            group.pk,
            GroupPermission(False, False, False, False),
        )

    def is_group_hidden(self, group):
        return (
            group.pk in self.configured_groups
            and not self.group(group).can_view
        )


def _group_queryset(queryset, key):
    result = {}
    for item in queryset:
        result.setdefault(item[key], []).append(item)
    return result


def _group_rules(queryset, key):
    result = {}
    for rule in queryset:
        result.setdefault(getattr(rule, key), []).append(rule)
    return result
