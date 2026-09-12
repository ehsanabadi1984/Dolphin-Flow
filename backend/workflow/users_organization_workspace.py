from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import Job, UserPreference

User = get_user_model()


class UserWorkspaceForm(forms.ModelForm):
    password1 = forms.CharField(label="رمز عبور", widget=forms.PasswordInput, required=False)
    password2 = forms.CharField(label="تکرار رمز عبور", widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = (
            "username",
            "first_name",
            "last_name",
            "email",
            "job",
            "is_active",
            "is_staff",
            "is_superuser",
            "groups",
            "user_permissions",
        )
        labels = {
            "username": "نام کاربری",
            "first_name": "نام",
            "last_name": "نام خانوادگی",
            "email": "ایمیل",
            "job": "شغل",
            "is_active": "فعال",
            "is_staff": "دسترسی Admin",
            "is_superuser": "Superuser",
            "groups": "گروه‌ها",
            "user_permissions": "مجوزهای مستقیم",
        }

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields["job"].queryset = Job.objects.order_by("name")
        self.fields["groups"].queryset = Group.objects.order_by("name")
        self.fields["user_permissions"].queryset = Permission.objects.select_related("content_type").order_by("content_type__app_label", "content_type__model", "codename")
        if not self.instance.pk:
            self.fields["is_staff"].initial = False
            self.fields["is_superuser"].initial = False
            self.fields["is_staff"].disabled = True
            self.fields["is_superuser"].disabled = True

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "رمزهای عبور یکسان نیستند.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        password = self.cleaned_data.get("password1")
        if password:
            obj.set_password(password)
        if not self.instance.pk:
            obj.is_staff = False
            obj.is_superuser = False
        if obj.pk == self.request.user.pk:
            obj.is_staff = True
            obj.is_superuser = True
        elif self.instance.pk and User.objects.filter(pk=obj.pk, is_superuser=True).exists() and not obj.is_superuser:
            raise PermissionDenied
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class JobWorkspaceForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ("name", "code", "description", "is_active")
        labels = {
            "name": "نام",
            "code": "کد",
            "description": "توضیحات",
            "is_active": "فعال",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class GroupWorkspaceForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ("name", "permissions")
        labels = {"name": "نام گروه", "permissions": "مجوزها"}


class UserPreferenceWorkspaceForm(forms.ModelForm):
    class Meta:
        model = UserPreference
        fields = ("session_timeout",)
        labels = {"session_timeout": "زمان انقضای نشست"}


def _workspace_url(tab="users", **params):
    url = reverse("users_organization_workspace")
    values = [f"tab={tab}"]
    values.extend(f"{key}={value}" for key, value in params.items() if value is not None)
    return f"{url}?{'&'.join(values)}"


def users_organization_workspace(request):
    if not (request.user.is_authenticated and request.user.is_active and request.user.is_superuser):
        raise PermissionDenied

    tab = request.GET.get("tab", "users")
    if tab not in {"users", "jobs", "groups"}:
        tab = "users"

    edit_id = request.GET.get("edit")
    editing_user = editing_job = editing_group = None
    if edit_id:
        if tab == "users":
            editing_user = get_object_or_404(User, pk=edit_id)
        elif tab == "jobs":
            editing_job = get_object_or_404(Job, pk=edit_id)
        elif tab == "groups":
            editing_group = get_object_or_404(Group, pk=edit_id)

    invalid_form = None
    invalid_preference_form = None

    if request.method == "POST":
        action = request.POST.get("action")
        object_id = request.POST.get("object_id")

        if action == "delete":
            if tab == "users":
                obj = get_object_or_404(User, pk=object_id)
                if obj.pk == request.user.pk or obj.is_superuser:
                    messages.error(request, "این حساب از طریق این بخش قابل حذف نیست.")
                else:
                    obj.delete()
                    messages.success(request, "کاربر حذف شد.")
            elif tab == "jobs":
                obj = get_object_or_404(Job, pk=object_id)
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, "این شغل قابل حذف نیست؛ هنوز برای کاربران استفاده می‌شود.")
                else:
                    messages.success(request, "شغل حذف شد.")
            elif tab == "groups":
                get_object_or_404(Group, pk=object_id).delete()
                messages.success(request, "گروه حذف شد.")
            return redirect(_workspace_url(tab))

        if action in {"save_user", "save_job", "save_group"}:
            if action == "save_user":
                obj = get_object_or_404(User, pk=object_id) if object_id else None
                form = UserWorkspaceForm(request, request.POST, instance=obj)
                if form.is_valid():
                    try:
                        saved = form.save()
                    except PermissionDenied:
                        raise
                    preference, _ = UserPreference.objects.get_or_create(user=saved)
                    pref_form = UserPreferenceWorkspaceForm(request.POST, instance=preference)
                    if pref_form.is_valid():
                        pref_form.save()
                    else:
                        invalid_preference_form = pref_form
                    messages.success(request, "اطلاعات کاربر با موفقیت ذخیره شد.")
                    if invalid_preference_form is None:
                        return redirect(_workspace_url("users"))
                invalid_form = form
            elif action == "save_job":
                obj = get_object_or_404(Job, pk=object_id) if object_id else None
                form = JobWorkspaceForm(request.POST, instance=obj)
                if form.is_valid():
                    form.save()
                    messages.success(request, "شغل با موفقیت ذخیره شد.")
                    return redirect(_workspace_url("jobs"))
                invalid_form = form
            else:
                obj = get_object_or_404(Group, pk=object_id) if object_id else None
                form = GroupWorkspaceForm(request.POST, instance=obj)
                if form.is_valid():
                    form.save()
                    messages.success(request, "گروه با موفقیت ذخیره شد.")
                    return redirect(_workspace_url("groups"))
                invalid_form = form

    users = User.objects.select_related("job").prefetch_related("groups").order_by("username")
    jobs = Job.objects.order_by("name")
    groups = Group.objects.prefetch_related("permissions").order_by("name")

    user_form = invalid_form if tab == "users" and isinstance(invalid_form, UserWorkspaceForm) else UserWorkspaceForm(request, instance=editing_user)
    job_form = invalid_form if tab == "jobs" and isinstance(invalid_form, JobWorkspaceForm) else JobWorkspaceForm(instance=editing_job)
    group_form = invalid_form if tab == "groups" and isinstance(invalid_form, GroupWorkspaceForm) else GroupWorkspaceForm(instance=editing_group)

    preference = None
    if editing_user:
        preference, _ = UserPreference.objects.get_or_create(user=editing_user)
    preference_form = invalid_preference_form or UserPreferenceWorkspaceForm(instance=preference)

    return render(
        request,
        "admin/workflow/users_organization_workspace.html",
        {
            "tab": tab,
            "users": users,
            "jobs": jobs,
            "groups": groups,
            "editing_user": editing_user,
            "editing_job": editing_job,
            "editing_group": editing_group,
            "user_form": user_form,
            "job_form": job_form,
            "group_form": group_form,
            "preference_form": preference_form,
        },
    )
