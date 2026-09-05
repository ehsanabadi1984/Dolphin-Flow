from django import forms

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
