from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import Job, UserPreference
from repairs.models import RepairForm

from .models import (
    Notification,
    WorkflowInstance,
    WorkflowMembership,
    WorkflowPermission,
    WorkflowStep,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
)

User = get_user_model()


class UserWorkspaceForm(forms.ModelForm):
    password1 = forms.CharField(label="رمز عبور", widget=forms.PasswordInput, required=False)
    password2 = forms.CharField(label="تکرار رمز عبور", widget=forms.PasswordInput, required=False)

    class Meta:
        model = User
        fields = (
            "username", "first_name", "last_name", "email", "job",
            "is_active", "is_staff", "is_superuser", "groups", "user_permissions",
        )
        labels = {
            "username": "نام کاربری", "first_name": "نام", "last_name": "نام خانوادگی",
            "email": "ایمیل", "job": "شغل", "is_active": "فعال",
            "is_staff": "دسترسی Admin", "is_superuser": "Superuser",
            "groups": "گروه‌ها", "user_permissions": "مجوزهای مستقیم",
        }

    def __init__(self, request, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.fields["job"].queryset = Job.objects.order_by("name")
        self.fields["groups"].queryset = Group.objects.order_by("name")
        self.fields["user_permissions"].queryset = Permission.objects.select_related("content_type").order_by(
            "content_type__app_label", "content_type__model", "codename"
        )
        if not self.instance.pk:
            self.fields["is_staff"].initial = False
            self.fields["is_superuser"].initial = False
            self.fields["is_staff"].disabled = True
            self.fields["is_superuser"].disabled = True

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if not self.instance.pk and not password1:
            self.add_error("password1", "برای ایجاد کاربر وارد کردن رمز عبور الزامی است.")
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
        elif obj.pk == self.request.user.pk:
            obj.is_staff = True
            obj.is_superuser = True
        elif User.objects.filter(pk=obj.pk, is_superuser=True).exists() and not obj.is_superuser:
            raise PermissionDenied

        if commit:
            obj.save()
            self.save_m2m()
        return obj


class JobWorkspaceForm(forms.ModelForm):
    class Meta:
        model = Job
        fields = ("name", "code", "description", "is_active")
        labels = {"name": "نام", "code": "کد", "description": "توضیحات", "is_active": "فعال"}
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


def _user_delete_dependencies(user):
    return {
        "memberships": list(
            WorkflowMembership.objects.filter(user=user).select_related("workflow")
        ),
        "assigned_steps": list(
            WorkflowStep.objects.filter(assigned_to=user).select_related("workflow")
        ),
        "workflow_permissions": list(
            WorkflowPermission.objects.filter(user=user)
            .select_related("workflow", "step", "transition")
        ),
        "started_instances": list(
            WorkflowInstance.objects.filter(started_by=user).select_related("workflow")
        ),
        "step_executions": list(
            WorkflowStepExecution.objects.filter(performed_by=user)
            .select_related("workflow_step__workflow", "workflow_step")
        ),
        "transition_executions": list(
            WorkflowTransitionExecution.objects.filter(performed_by=user)
            .select_related("transition__workflow", "transition")
        ),
        "notifications": list(
            Notification.objects.filter(recipient=user).select_related("workflow_instance")
        ),
        "repair_forms": list(
            RepairForm.objects.filter(created_by=user).select_related("customer")
        ),
    }


def _user_delete_analysis(user):
    dependencies = _user_delete_dependencies(user)
    operational = (
        dependencies["memberships"]
        + dependencies["assigned_steps"]
        + dependencies["workflow_permissions"]
    )
    historical = (
        dependencies["started_instances"]
        + dependencies["step_executions"]
        + dependencies["transition_executions"]
        + dependencies["notifications"]
        + dependencies["repair_forms"]
    )
    return {
        "dependencies": dependencies,
        "operational": operational,
        "historical": historical,
        "can_hard_delete": not historical,
        "has_dependencies": bool(operational or historical),
    }


def _transfer_operational_dependencies(user, target):
    for membership in list(WorkflowMembership.objects.filter(user=user).select_related("workflow")):
        existing = WorkflowMembership.objects.filter(
            workflow=membership.workflow, user=target
        ).first()
        if existing:
            membership.delete()
        else:
            membership.user = target
            membership.save(update_fields=["user"])

    WorkflowStep.objects.filter(assigned_to=user).update(assigned_to=target)
    WorkflowPermission.objects.filter(user=user).update(user=target)


def users_organization_workspace(request):
    if not (request.user.is_authenticated and request.user.is_active and request.user.is_superuser):
        raise PermissionDenied

    tab = request.GET.get("tab", "users")
    if tab not in {"users", "jobs", "groups"}:
        tab = "users"

    edit_id = request.GET.get("edit")
    editing_user = editing_job = editing_group = None
    delete_analysis = None
    delete_user = None
    if edit_id:
        if tab == "users":
            editing_user = get_object_or_404(User, pk=edit_id)
        elif tab == "jobs":
            editing_job = get_object_or_404(Job, pk=edit_id)
        else:
            editing_group = get_object_or_404(Group, pk=edit_id)

    invalid_form = None
    invalid_preference_form = None

    if request.method == "POST":
        action = request.POST.get("action")
        object_id = request.POST.get("object_id")

        if action == "delete":
            if tab == "users":
                obj = get_object_or_404(User, pk=object_id)
                delete_analysis = _user_delete_analysis(obj)
                delete_user = obj
                target_id = request.POST.get("target_user_id")
                mode = request.POST.get("delete_mode", "")

                if not delete_analysis["has_dependencies"]:
                    obj.delete()
                    messages.success(request, "کاربر حذف شد.")
                    return redirect(_workspace_url("users"))

                if mode == "deactivate":
                    obj.is_active = False
                    obj.save(update_fields=["is_active"])
                    messages.success(request, "کاربر غیرفعال شد و سوابق او حفظ شد.")
                    return redirect(_workspace_url("users"))

                if mode == "transfer_delete":
                    target = get_object_or_404(User, pk=target_id) if target_id else None
                    if not target or target.pk == obj.pk:
                        messages.error(request, "برای انتقال مسئولیت‌ها یک کاربر مقصد معتبر انتخاب کنید.")
                    elif delete_analysis["historical"]:
                        messages.error(request, "این کاربر سابقه تاریخی دارد؛ برای حفظ سابقه، فقط غیرفعال‌سازی مجاز است.")
                    else:
                        try:
                            with transaction.atomic():
                                _transfer_operational_dependencies(obj, target)
                                obj.delete()
                        except ProtectedError:
                            messages.error(request, "حذف کاربر به دلیل یک وابستگی محافظت‌شده انجام نشد؛ کاربر غیرفعال باقی بماند.")
                        else:
                            messages.success(request, f"مسئولیت‌های کاربر به «{target}» منتقل و کاربر حذف شد.")
                            return redirect(_workspace_url("users"))

                return render(
                    request,
                    "admin/workflow/users_organization_workspace.html",
                    {
                        "tab": "users",
                        "users": User.objects.select_related("job").prefetch_related("groups").order_by("username"),
                        "jobs": Job.objects.order_by("name"),
                        "groups": Group.objects.prefetch_related("permissions").order_by("name"),
                        "editing_user": editing_user or obj,
                        "editing_job": editing_job,
                        "editing_group": editing_group,
                        "user_form": UserWorkspaceForm(request, instance=editing_user or obj),
                        "job_form": JobWorkspaceForm(instance=editing_job),
                        "group_form": GroupWorkspaceForm(instance=editing_group),
                        "preference_form": UserPreferenceWorkspaceForm(
                            instance=UserPreference.objects.filter(user=editing_user or obj).first()
                        ),
                        "delete_analysis": delete_analysis,
                        "delete_user": delete_user,
                        "delete_target_users": User.objects.filter(is_active=True).exclude(pk=obj.pk).order_by("username"),
                    },
                )
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

        if action == "save_user":
            obj = get_object_or_404(User, pk=object_id) if object_id else None
            editing_user = obj
            form = UserWorkspaceForm(request, request.POST, instance=obj)
            if form.is_valid():
                saved = form.save()
                preference, _ = UserPreference.objects.get_or_create(user=saved)
                pref_form = UserPreferenceWorkspaceForm(request.POST, instance=preference)
                if pref_form.is_valid():
                    pref_form.save()
                else:
                    invalid_preference_form = pref_form
                if invalid_preference_form is None:
                    messages.success(request, "اطلاعات کاربر با موفقیت ذخیره شد.")
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
        elif action == "save_group":
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

    user_form = invalid_form if isinstance(invalid_form, UserWorkspaceForm) else UserWorkspaceForm(request, instance=editing_user)
    job_form = invalid_form if isinstance(invalid_form, JobWorkspaceForm) else JobWorkspaceForm(instance=editing_job)
    group_form = invalid_form if isinstance(invalid_form, GroupWorkspaceForm) else GroupWorkspaceForm(instance=editing_group)

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
            "delete_analysis": delete_analysis,
            "delete_user": delete_user,
            "delete_target_users": User.objects.filter(is_active=True).exclude(pk=editing_user.pk).order_by("username") if editing_user else User.objects.none(),
        },
    )
