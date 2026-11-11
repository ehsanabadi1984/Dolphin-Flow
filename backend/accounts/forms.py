from django import forms
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
            regex=r"^\\+?[0-9]{8,15}$",
            message="شماره را با ۸ تا ۱۵ رقم و بدون فاصله وارد کنید.",
        )],
        widget=forms.TextInput(attrs={
            "class": "df-form-input", "inputmode": "tel",
            "autocomplete": "tel", "placeholder": "989121234567",
        }),
    )

    def clean_phone_number(self):
        return self.cleaned_data["phone_number"].strip()


class SMSVerificationForm(forms.Form):
    verification_code = forms.CharField(
        label="کد تأیید", min_length=6, max_length=6,
        validators=[RegexValidator(
            regex=r"^[0-9]{6}$",
            message="کد تأیید باید دقیقاً ۶ رقم باشد.",
        )],
        widget=forms.TextInput(attrs={
            "class": "df-form-input", "inputmode": "numeric",
            "autocomplete": "one-time-code", "placeholder": "کد ۶ رقمی",
        }),
    )
