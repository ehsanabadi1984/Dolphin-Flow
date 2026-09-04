from django.apps import AppConfig


class WorkflowConfig(AppConfig):
    name = "workflow"

    def ready(self):
        from .models import FormField
        from .form_file_models import FormFile  # noqa: F401
        from .formula_bootstrap import bootstrap_formula_system
        from django.core.signals import request_started

        model_field = FormField._meta.get_field("field_type")
        choices = list(model_field.choices or [])
        if not any(value == "FORMULA" for value, _ in choices):
            choices.append(("FORMULA", "فرمول"))
        if not any(value == "FILE" for value, _ in choices):
            choices.append(("FILE", "بارگذاری فایل"))
        model_field.choices = choices

        request_started.connect(
            lambda sender, **kwargs: bootstrap_formula_system(),
            weak=False,
            dispatch_uid="workflow.formula_bootstrap_apps_ready",
        )
