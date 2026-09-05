from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import SessionTimeoutForm
from .models import UserPreference


def _session_timeout_context(request, page_title, page_breadcrumb):
    preference, _ = UserPreference.objects.get_or_create(user=request.user)
    return {
        "session_timeout_form": SessionTimeoutForm(instance=preference),
        "page_title": page_title,
        "page_breadcrumb": page_breadcrumb,
    }


def _save_session_timeout(request):
    preference, _ = UserPreference.objects.get_or_create(user=request.user)
    form = SessionTimeoutForm(request.POST, instance=preference)
    if form.is_valid():
        form.save()
        request.session.set_expiry(preference.session_timeout)
        messages.success(request, "زمان انقضای نشست با موفقیت ذخیره شد.")
        return True
    return form


@login_required
def dashboard(request):
    return render(
        request,
        "operator_panel/dashboard.html",
    )


@login_required
def profile(request):
    if request.method == "POST" and "session_timeout" in request.POST:
        result = _save_session_timeout(request)
        if result is True:
            return redirect("accounts:profile")
        session_timeout_form = result
    else:
        preference, _ = UserPreference.objects.get_or_create(user=request.user)
        session_timeout_form = SessionTimeoutForm(instance=preference)

    return render(
        request,
        "accounts/profile.html",
        {
            "user": request.user,
            "session_timeout_form": session_timeout_form,
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
    if request.method == "POST" and "session_timeout" in request.POST:
        result = _save_session_timeout(request)
        if result is True:
            return redirect("accounts:settings")
        session_timeout_form = result
    else:
        preference, _ = UserPreference.objects.get_or_create(user=request.user)
        session_timeout_form = SessionTimeoutForm(instance=preference)

    return render(
        request,
        "accounts/settings.html",
        {
            "session_timeout_form": session_timeout_form,
            "page_title": "تنظیمات",
            "page_breadcrumb": "تنظیمات",
        },
    )
