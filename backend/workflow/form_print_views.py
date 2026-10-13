from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from workflow.form_print_services import FormPrintDataService
from workflow.models import WorkflowInstance


@login_required
def form_print_preview(request, instance_id):
    """Render a permission-filtered, browser-based print preview."""
    instance = get_object_or_404(
        WorkflowInstance.objects.select_related(
            "workflow",
            "current_step",
        ),
        pk=instance_id,
    )
    print_data = FormPrintDataService.prepare(
        instance=instance,
        user=request.user,
    )
    if print_data is None:
        from django.http import Http404
        raise Http404("فرم قابل چاپ برای این فرایند پیدا نشد.")

    return render(
        request,
        "operator_panel/form_print_preview.html",
        {
            "instance": instance,
            "print_data": print_data,
        },
    )
