from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def dashboard(request):
    return render(
        request,
        "operator_panel/dashboard.html",
    )


@login_required
def profile(request):
    return render(
        request,
        "accounts/profile.html",
        {
            "user": request.user,
            "page_title": "پروفایل من",
            "page_breadcrumb": "پروفایل من",
        },
    )


@login_required
def permissions(request):
    return render(
        request,
        "accounts/permissions.html",
        {
            "groups": request.user.groups.all(),
            "permissions": request.user.get_all_permissions(),
            "page_title": "دسترسی‌های من",
            "page_breadcrumb": "دسترسی‌های من",
        },
    )


@login_required
def activity(request):
    return render(
        request,
        "accounts/activity.html",
        {
            "page_title": "فعالیت‌های من",
            "page_breadcrumb": "فعالیت‌های من",
        },
    )


@login_required
def settings(request):
    return render(
        request,
        "accounts/settings.html",
        {
            "page_title": "تنظیمات",
            "page_breadcrumb": "تنظیمات",
        },
    )
