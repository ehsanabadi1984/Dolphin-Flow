from django.db.models.signals import pre_save
from django.dispatch import receiver

from .formula_services import FormulaError, FormulaService
from .models import FormData, FormDefinition


@receiver(
    pre_save,
    sender=FormData,
    dispatch_uid="workflow.persist_calculated_formulas",
)
def persist_calculated_formulas(sender, instance, **kwargs):
    """
    Calculate Formula fields before FormData is written.

    FormData is assembled by the dynamic form service before save, so
    calculating here guarantees that the persisted snapshot contains
    server-derived formula values. Unlike the previous post_save handler,
    this does not issue a second FormData.save() and therefore avoids a
    recursive signal invocation.
    """
    workflow_instance = getattr(instance, "instance", None)
    workflow = getattr(workflow_instance, "workflow", None)
    if workflow is None:
        return

    form = (
        FormDefinition.objects
        .filter(
            workflow=workflow,
            is_active=True,
        )
        .first()
    )
    if form is None:
        return

    try:
        instance.data = FormulaService.calculate_context_data(
            form=form,
            data=instance.data or {},
        )
    except FormulaError:
        # Formula configuration errors must not turn an otherwise valid
        # FormData save into a 500 response. Admin-side formula validation
        # remains responsible for reporting invalid formula definitions.
        return
