from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .dashboard_services import DashboardService


@login_required
def dashboard(request):
    context = DashboardService(request.user).get_context()
    return render(
        request,
        "operator_panel/dashboard.html",
        {
            "user": request.user,
            **context,
        },
    )
