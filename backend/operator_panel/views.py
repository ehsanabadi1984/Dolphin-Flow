from django.contrib.auth.decorators import login_required
from django.shortcuts import render



@login_required
def dashboard(request):
    return render(
        request,
        "operator_panel/dashboard.html",
        {
            "user": request.user,
        },
    )



# Create your views here.
