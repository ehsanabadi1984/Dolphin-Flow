from django.db.models.signals import post_save
from django.dispatch import receiver

from .formula_services import FormulaError, FormulaService
from .models import FormData, FormDefinition


@receiver(
    post_save,
    sender=FormData,
    dispatch_uid="workflow.persist_calculated_formulas",
)
def persist_calculated_formulas(sender, instance, **kwargs):
    """
    Persist calculated Formula field values after FormData is saved.

    Formula values are derived from the saved input data on the server so
    client-side values can never become the source of truth.
    """
    workflow = getattr(instance.instance, "workflow", None)
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
        calculated_data = FormulaService.calculate_context_data(
            form=form,
            data=instance.data or {},
        )
    except FormulaError:
        # Formula configuration errors are handled by the formula admin
        # validation path. They must not turn an otherwise valid form save
        # into a 500 response here.
        return

    current_data = instance.data or {}
    if calculated_data == current_data:
        return

    instance.data = calculated_data
    instance.save(update_fields=["data", "updated_at"])
