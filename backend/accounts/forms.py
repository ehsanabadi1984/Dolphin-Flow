from django import forms
from django.conf import settings
from django.core.validators import RegexValidator

from .models import UserPreference


class SessionTimeoutForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = ["session_timeout"]
        labels = {"session_timeout": "زمان انقضای نشست"}
        widgets = {
            "session_timeout": forms.Select(
                attrs={"class": "df-form-input"},
            ),
        }


class SMSPhoneForm(forms.Form):
    phone_number = forms.CharField(
        label="شماره موبایل",
        max_length=16,
        validators=[RegexValidator(
            regex=r"^[+]?[1-9][0-9]{7,14}$",
            message="شماره را با ۸ تا ۱۵ رقم و بدون فاصله وارد کنید.",
        )],
        widget=forms.TextInput(attrs={
            "class": "df-form-input", "inputmode": "tel",
            "autocomplete": "tel", "placeholder": "989121234567",
        }),
    )

    def clean_phone_number(self):
        return self.cleaned_data["phone_number"].strip().lstrip("+")


class SMSVerificationForm(forms.Form):
    otp_length = max(4, min(8, settings.SMS_OTP_LENGTH))
    verification_code = forms.CharField(
        label="کد تأیید", min_length=otp_length, max_length=otp_length,
        validators=[RegexValidator(
            regex=rf"^[0-9]{{{otp_length}}}$",
            message=f"کد تأیید باید دقیقاً {otp_length} رقم باشد.",
        )],
        widget=forms.TextInput(attrs={
            "class": "df-form-input", "inputmode": "numeric",
            "autocomplete": "one-time-code", "placeholder": f"کد {otp_length} رقمی",
        }),
    )
