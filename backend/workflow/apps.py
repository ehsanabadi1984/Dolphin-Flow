from django.apps import AppConfig


class WorkflowConfig(AppConfig):
    name = "workflow"

    def ready(self):
        from .models import FormField, WorkflowInstance, WorkflowPermission
        from .form_file_models import FormFile  # noqa: F401
        from .history_models import HistoryConfiguration, HistoryField  # noqa: F401
        from django.contrib.admin import autodiscover
        autodiscover()
        from .history_admin import HistoryConfigurationAdmin  # noqa: F401
        from .formula_bootstrap import bootstrap_formula_system
        from . import signals  # noqa: F401
        from django.core.signals import request_started

        # Human-readable form number: YYMMDD-NNNNNN.
        # It is derived from the existing instance creation date and PK,
        # so no database field or migration is required.
        if not hasattr(WorkflowInstance, "form_number"):
            WorkflowInstance.form_number = property(
                lambda instance: (
                    f"{instance.started_at:%y%m%d}-{instance.pk:06d}"
                )
            )

        model_field = FormField._meta.get_field("field_type")
        choices = list(model_field.choices or [])
        if not any(value == "FORMULA" for value, _ in choices):
            choices.append(("FORMULA", "فرمول"))
        if not any(value == "FILE" for value, _ in choices):
            choices.append(("FILE", "بارگذاری فایل"))
        model_field.choices = choices

        permission_field = WorkflowPermission._meta.get_field("action")
        permission_choices = list(permission_field.choices or [])
        if not any(value == "HISTORY" for value, _ in permission_choices):
            permission_choices.append(("HISTORY", "سوابق"))
        permission_field.choices = permission_choices

        request_started.connect(
            lambda sender, **kwargs: bootstrap_formula_system(),
            weak=False,
            dispatch_uid="workflow.formula_bootstrap_apps_ready",
        )
