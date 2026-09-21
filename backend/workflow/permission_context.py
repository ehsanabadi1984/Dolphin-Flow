from dataclasses import dataclass
from typing import FrozenSet


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
    ):
        self.roles = roles
        self.normal_fields = normal_fields
        self.repeatable_fields = repeatable_fields
        self.groups = groups

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

        return cls(
            roles=roles,
            normal_fields=normal_fields,
            repeatable_fields=repeatable_fields,
            groups=groups,
        )

    @staticmethod
    def _field_permission(*, field, step, user, roles):
        access_rules = field.access_rules.filter(step=step)

        user_rule = access_rules.filter(
            user=user,
        ).first()

        if user_rule is not None:
            return FieldPermission(
                can_view=user_rule.can_view,
                can_edit=user_rule.can_edit,
            )

        role_rules = access_rules.filter(
            role__in=roles,
            user__isnull=True,
        )

        return FieldPermission(
            can_view=role_rules.filter(
                can_view=True,
            ).exists(),
            can_edit=role_rules.filter(
                can_edit=True,
            ).exists(),
        )

    @staticmethod
    def _group_permission(*, group, step, user, roles):
        access_rules = group.access_rules.filter(step=step)

        user_rule = access_rules.filter(
            user=user,
        ).first()

        if user_rule is not None:
            return GroupPermission(
                can_view=user_rule.can_view,
                can_edit=user_rule.can_edit,
                can_add=user_rule.can_add,
                can_delete=user_rule.can_delete,
            )

        role_rules = access_rules.filter(
            role__in=roles,
            user__isnull=True,
        )

        return GroupPermission(
            can_view=role_rules.filter(
                can_view=True,
            ).exists(),
            can_edit=role_rules.filter(
                can_edit=True,
            ).exists(),
            can_add=role_rules.filter(
                can_add=True,
            ).exists(),
            can_delete=role_rules.filter(
                can_delete=True,
            ).exists(),
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

    def group(self, group):
        return self.groups.get(
            group.pk,
            GroupPermission(False, False, False, False),
        )
