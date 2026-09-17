from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from workflow.history_browser_service import HistoryBrowserService


@login_required
def history_list(request):
    history = HistoryBrowserService.get_history(user=request.user)

    return render(
        request,
        "operator_panel/history_list.html",
        {
            "history": history,
            "page_title": "تاریخچه",
            "page_breadcrumb": "تاریخچه",
        },
    )
