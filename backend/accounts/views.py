from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from workflow.models import WorkflowSMSSettings

from .forms import SMSPhoneForm, SMSVerificationForm
from .services import request_sms_verification, verify_sms_verification_code

from .forms import SessionTimeoutForm
from .models import UserContactMethod, UserPreference


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
    preference, _ = UserPreference.objects.get_or_create(user=request.user)
    contact = request.user.contact_methods.filter(
        channel_type=UserContactMethod.ChannelType.SMS,
    ).first()
    session_timeout_form = SessionTimeoutForm(instance=preference)
    phone_form = SMSPhoneForm(initial={"phone_number": contact.value if contact else ""})
    verification_form = SMSVerificationForm()

    if request.method == "POST":
        action = request.POST.get("sms_action")
        if action == "save_phone":
            phone_form = SMSPhoneForm(request.POST)
            if phone_form.is_valid():
                try:
                    sent = request_sms_verification(request.user, phone_form.cleaned_data["phone_number"])
                except Exception as exc:
                    from django.core.exceptions import ValidationError
                    if isinstance(exc, ValidationError):
                        messages.error(request, " ".join(exc.messages))
                    else:
                        messages.error(request, "ثبت شماره و ارسال کد تأیید انجام نشد.")
                else:
                    if sent:
                        messages.success(request, "کد تأیید ارسال شد. پس از دریافت، آن را در بخش تأیید شماره وارد کنید.")
                    else:
                        messages.info(request, "این شماره قبلاً تأیید شده و فعال است.")
                    return redirect("accounts:settings")
        elif action == "verify_phone":
            verification_form = SMSVerificationForm(request.POST)
            if verification_form.is_valid():
                try:
                    verify_sms_verification_code(request.user, verification_form.cleaned_data["verification_code"])
                except Exception as exc:
                    from django.core.exceptions import ValidationError
                    if isinstance(exc, ValidationError):
                        messages.error(request, " ".join(exc.messages))
                    else:
                        messages.error(request, "تأیید شماره انجام نشد.")
                else:
                    messages.success(request, "شماره موبایل با موفقیت تأیید شد.")
                    return redirect("accounts:settings")
        elif action == "toggle_sms":
            enabled = request.POST.get("sms_enabled") == "1"
            if enabled and not (contact and contact.is_active and contact.is_verified):
                messages.error(request, "برای فعال‌کردن دریافت پیامک، ابتدا باید شماره موبایل خود را ثبت و تأیید کنید.")
            else:
                preference.sms_notifications_enabled = enabled
                preference.save(update_fields=("sms_notifications_enabled",))
                messages.success(request, "تنظیم دریافت پیامک ذخیره شد." if enabled else "دریافت پیامک برای حساب شما غیرفعال شد.")
                return redirect("accounts:settings")
        elif "session_timeout" in request.POST:
            result = _save_session_timeout(request)
            if result is True:
                return redirect("accounts:settings")
            session_timeout_form = result

    contact = request.user.contact_methods.filter(
        channel_type=UserContactMethod.ChannelType.SMS,
    ).first()
    return render(
        request,
        "accounts/settings.html",
        {
            "session_timeout_form": session_timeout_form,
            "user_preference": preference,
            "sms_contact": contact,
            "sms_global_enabled": WorkflowSMSSettings.objects.filter(pk=1, is_enabled=True).exists(),
            "sms_phone_form": phone_form,
            "sms_verification_form": verification_form,
            "page_title": "تنظیمات",
            "page_breadcrumb": "تنظیمات",
        },
    )
