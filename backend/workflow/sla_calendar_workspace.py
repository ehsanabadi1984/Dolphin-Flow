from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import (
    BusinessCalendar,
    CalendarException,
    CalendarExceptionInterval,
    WeeklySchedule,
    WorkingInterval,
    Workflow,
    WorkflowStep,
    WorkflowStepSLA,
)


class BusinessCalendarWorkspaceForm(forms.ModelForm):
    class Meta:
        model = BusinessCalendar
        fields = ("name", "timezone", "is_active")


class WeeklyScheduleWorkspaceForm(forms.ModelForm):
    class Meta:
        model = WeeklySchedule
        fields = ("weekday", "is_working")


class WorkingIntervalWorkspaceForm(forms.ModelForm):
    class Meta:
        model = WorkingInterval
        fields = ("start_time", "end_time")
        widgets = {
            "start_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "end_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
        }


class BulkWorkingScheduleWorkspaceForm(forms.Form):
    weekdays = forms.MultipleChoiceField(
        label="روزهای کاری",
        choices=WeeklySchedule._meta.get_field("weekday").choices,
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )

    def clean(self):
        cleaned_data = super().clean()
        raw_starts = self.data.getlist("bulk_start_time")
        raw_ends = self.data.getlist("bulk_end_time")

        if not raw_starts or not raw_ends:
            raise forms.ValidationError("حداقل یک بازه کاری باید وارد شود.")
        if len(raw_starts) != len(raw_ends):
            raise forms.ValidationError("بازه‌های کاری کامل نیستند.")

        intervals = []
        for index, (raw_start, raw_end) in enumerate(zip(raw_starts, raw_ends), start=1):
            try:
                start_time = forms.TimeField(input_formats=["%H:%M", "%H:%M:%S"]).clean(raw_start)
                end_time = forms.TimeField(input_formats=["%H:%M", "%H:%M:%S"]).clean(raw_end)
            except forms.ValidationError:
                raise forms.ValidationError(f"بازه شماره {index} زمان معتبری ندارد.")

            if start_time >= end_time:
                raise forms.ValidationError(
                    f"بازه شماره {index}: زمان شروع باید قبل از زمان پایان باشد."
                )
            intervals.append((start_time, end_time))

        ordered = sorted(intervals)
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] < previous[1]:
                raise forms.ValidationError("بازه‌های واردشده نباید با یکدیگر تداخل داشته باشند.")

        cleaned_data["intervals"] = intervals
        return cleaned_data


class CalendarExceptionWorkspaceForm(forms.ModelForm):
    class Meta:
        model = CalendarException
        fields = ("date", "status", "title", "description")
        widgets = {
            "date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 2}),
        }


class CalendarExceptionIntervalWorkspaceForm(forms.ModelForm):
    class Meta:
        model = CalendarExceptionInterval
        fields = ("start_time", "end_time")
        widgets = {
            "start_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "end_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
        }


class WorkflowStepSLAWorkspaceForm(forms.ModelForm):
    class Meta:
        model = WorkflowStepSLA
        fields = ("calendar", "duration", "warning_before", "is_active")
        widgets = {
            "duration": forms.TextInput(attrs={"placeholder": "مثلاً 1 08:00:00"}),
            "warning_before": forms.TextInput(attrs={"placeholder": "مثلاً 04:00:00"}),
        }


def _workspace_url(tab="calendars", **params):
    url = reverse("sla_calendar_workspace")
    values = [f"tab={tab}"]
    for key, value in params.items():
        if value is not None:
            values.append(f"{key}={value}")
    return f"{url}?{'&'.join(values)}"


def _bulk_working_schedule(calendar, form):
    weekdays = [int(value) for value in form.cleaned_data["weekdays"]]
    intervals = form.cleaned_data["intervals"]

    with transaction.atomic():
        for weekday in weekdays:
            schedule, _ = WeeklySchedule.objects.get_or_create(
                calendar=calendar,
                weekday=weekday,
                defaults={"is_working": True},
            )
            if not schedule.is_working:
                schedule.is_working = True
                schedule.save(update_fields=["is_working"])

            for start_time, end_time in intervals:
                interval = WorkingInterval(
                    weekly_schedule=schedule,
                    start_time=start_time,
                    end_time=end_time,
                )
                interval.full_clean()
                interval.save()


def sla_calendar_workspace(request):
    tab = request.GET.get("tab", "calendars")
    if tab not in {"calendars", "sla"}:
        tab = "calendars"

    selected_calendar_id = request.GET.get("calendar")
    selected_schedule_id = request.GET.get("schedule")
    selected_exception_id = request.GET.get("exception")
    selected_step_id = request.GET.get("step")

    selected_calendar = (
        get_object_or_404(BusinessCalendar, pk=selected_calendar_id)
        if selected_calendar_id else None
    )
    selected_schedule = None
    selected_exception = None
    selected_step = None

    if selected_schedule_id:
        selected_schedule = get_object_or_404(WeeklySchedule, pk=selected_schedule_id)
        if selected_calendar and selected_schedule.calendar_id != selected_calendar.pk:
            selected_schedule = None
        elif not selected_calendar:
            selected_calendar = selected_schedule.calendar

    if selected_exception_id:
        selected_exception = get_object_or_404(CalendarException, pk=selected_exception_id)
        if selected_calendar and selected_exception.calendar_id != selected_calendar.pk:
            selected_exception = None
        elif not selected_calendar:
            selected_calendar = selected_exception.calendar

    if selected_step_id:
        selected_step = get_object_or_404(WorkflowStep, pk=selected_step_id)

    if request.method == "POST":
        action = request.POST.get("action")
        object_type = request.POST.get("object_type")

        if action == "delete":
            if object_type == "calendar":
                obj = get_object_or_404(BusinessCalendar, pk=request.POST.get("object_id"))
                name = str(obj)
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, f"«{name}» قابل حذف نیست؛ هنوز در داده‌های وابسته استفاده می‌شود.")
                else:
                    messages.success(request, f"«{name}» حذف شد.")
                return redirect(_workspace_url("calendars"))

            if object_type == "schedule":
                obj = get_object_or_404(WeeklySchedule, pk=request.POST.get("object_id"))
                calendar_id = obj.calendar_id
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, "این برنامه هفتگی قابل حذف نیست؛ داده‌های وابسته وجود دارد.")
                else:
                    messages.success(request, "برنامه هفتگی حذف شد.")
                return redirect(_workspace_url("calendars", calendar=calendar_id))

            if object_type == "working_interval":
                obj = get_object_or_404(WorkingInterval, pk=request.POST.get("object_id"))
                schedule = obj.weekly_schedule
                obj.delete()
                messages.success(request, "بازه کاری حذف شد.")
                return redirect(_workspace_url("calendars", calendar=schedule.calendar_id, schedule=schedule.pk))

            if object_type == "exception":
                obj = get_object_or_404(CalendarException, pk=request.POST.get("object_id"))
                calendar_id = obj.calendar_id
                try:
                    obj.delete()
                except ProtectedError:
                    messages.error(request, "این استثنا قابل حذف نیست؛ داده‌های وابسته وجود دارد.")
                else:
                    messages.success(request, "استثنای تقویم حذف شد.")
                return redirect(_workspace_url("calendars", calendar=calendar_id))

            if object_type == "exception_interval":
                obj = get_object_or_404(CalendarExceptionInterval, pk=request.POST.get("object_id"))
                exception = obj.exception
                obj.delete()
                messages.success(request, "بازه استثنا حذف شد.")
                return redirect(_workspace_url("calendars", calendar=exception.calendar_id, exception=exception.pk))

            if object_type == "sla":
                obj = get_object_or_404(WorkflowStepSLA, pk=request.POST.get("object_id"))
                step_id = obj.step_id
                obj.delete()
                messages.success(request, "تنظیمات SLA حذف شد.")
                return redirect(_workspace_url("sla", step=step_id))

        if action in {"add", "edit", "bulk_add"}:
            instance = None
            form = None
            redirect_params = {}

            if object_type == "bulk_working_schedule":
                calendar = get_object_or_404(BusinessCalendar, pk=request.POST.get("calendar_id"))
                form = BulkWorkingScheduleWorkspaceForm(request.POST)
                redirect_params = {"calendar": calendar.pk}
                if form.is_valid():
                    try:
                        _bulk_working_schedule(calendar, form)
                    except forms.ValidationError as exc:
                        form.add_error(None, exc)
                    else:
                        days_count = len(form.cleaned_data["weekdays"])
                        intervals_count = len(form.cleaned_data["intervals"])
                        messages.success(
                            request,
                            f"برای {days_count} روز، {intervals_count} بازه کاری اضافه شد.",
                        )
                        return redirect(_workspace_url("calendars", **redirect_params))
                messages.error(request, "اطلاعات افزودن گروهی معتبر نیست.")
                invalid_form = form
            else:
                if object_type == "calendar":
                    instance = get_object_or_404(BusinessCalendar, pk=request.POST.get("object_id")) if action == "edit" else None
                    form = BusinessCalendarWorkspaceForm(request.POST, instance=instance)
                elif object_type == "schedule":
                    calendar = get_object_or_404(BusinessCalendar, pk=request.POST.get("calendar_id"))
                    instance = get_object_or_404(WeeklySchedule, pk=request.POST.get("object_id"), calendar=calendar) if action == "edit" else WeeklySchedule(calendar=calendar)
                    form = WeeklyScheduleWorkspaceForm(request.POST, instance=instance)
                    redirect_params = {"calendar": calendar.pk}
                elif object_type == "working_interval":
                    schedule = get_object_or_404(WeeklySchedule, pk=request.POST.get("schedule_id"))
                    instance = get_object_or_404(WorkingInterval, pk=request.POST.get("object_id"), weekly_schedule=schedule) if action == "edit" else WorkingInterval(weekly_schedule=schedule)
                    form = WorkingIntervalWorkspaceForm(request.POST, instance=instance)
                    redirect_params = {"calendar": schedule.calendar_id, "schedule": schedule.pk}
                elif object_type == "exception":
                    calendar = get_object_or_404(BusinessCalendar, pk=request.POST.get("calendar_id"))
                    instance = get_object_or_404(CalendarException, pk=request.POST.get("object_id"), calendar=calendar) if action == "edit" else CalendarException(calendar=calendar)
                    form = CalendarExceptionWorkspaceForm(request.POST, instance=instance)
                    redirect_params = {"calendar": calendar.pk}
                elif object_type == "exception_interval":
                    exception = get_object_or_404(CalendarException, pk=request.POST.get("exception_id"))
                    instance = get_object_or_404(CalendarExceptionInterval, pk=request.POST.get("object_id"), exception=exception) if action == "edit" else CalendarExceptionInterval(exception=exception)
                    form = CalendarExceptionIntervalWorkspaceForm(request.POST, instance=instance)
                    redirect_params = {"calendar": exception.calendar_id, "exception": exception.pk}
                elif object_type == "sla":
                    step = get_object_or_404(WorkflowStep, pk=request.POST.get("step_id"))
                    instance = get_object_or_404(WorkflowStepSLA, pk=request.POST.get("object_id"), step=step) if action == "edit" else WorkflowStepSLA(step=step)
                    form = WorkflowStepSLAWorkspaceForm(request.POST, instance=instance)
                    redirect_params = {"step": step.pk}
                else:
                    messages.error(request, "نوع عملیات نامعتبر است.")
                    return redirect(_workspace_url(tab))

                if form.is_valid():
                    obj = form.save(commit=False)
                    obj.save()
                    messages.success(request, f"«{obj}» {'ذخیره شد' if instance and instance.pk else 'ایجاد شد'}.")
                    if object_type == "calendar":
                        return redirect(_workspace_url("calendars", calendar=obj.pk))
                    return redirect(_workspace_url(tab, **redirect_params))

                messages.error(request, "اطلاعات واردشده معتبر نیست.")
                invalid_form = form
        else:
            invalid_form = None
    else:
        invalid_form = None

    calendars = BusinessCalendar.objects.all().order_by("name")
    schedules = selected_calendar.weekly_schedules.all().order_by("weekday") if selected_calendar else WeeklySchedule.objects.none()
    exceptions = selected_calendar.exceptions.all().order_by("date") if selected_calendar else CalendarException.objects.none()
    working_intervals = selected_schedule.intervals.all().order_by("start_time") if selected_schedule else WorkingInterval.objects.none()
    exception_intervals = selected_exception.intervals.all().order_by("start_time") if selected_exception else CalendarExceptionInterval.objects.none()

    workflows = Workflow.objects.all().order_by("name")
    selected_workflow = selected_step.workflow if selected_step else None
    steps = selected_workflow.steps.all().order_by("order") if selected_workflow else WorkflowStep.objects.none()
    selected_sla = getattr(selected_step, "sla", None) if selected_step else None

    object_type = request.POST.get("object_type") if request.method == "POST" else None
    calendar_form = invalid_form if object_type == "calendar" else BusinessCalendarWorkspaceForm(instance=selected_calendar)
    schedule_form = invalid_form if object_type == "schedule" else WeeklyScheduleWorkspaceForm()
    interval_form = invalid_form if object_type == "working_interval" else WorkingIntervalWorkspaceForm()
    bulk_form = invalid_form if object_type == "bulk_working_schedule" else BulkWorkingScheduleWorkspaceForm()
    exception_form = invalid_form if object_type == "exception" else CalendarExceptionWorkspaceForm(instance=selected_exception)
    exception_interval_form = invalid_form if object_type == "exception_interval" else CalendarExceptionIntervalWorkspaceForm()
    sla_form = invalid_form if object_type == "sla" else WorkflowStepSLAWorkspaceForm(instance=selected_sla)

    return render(
        request,
        "admin/workflow/sla_calendar_workspace.html",
        {
            "tab": tab,
            "calendars": calendars,
            "selected_calendar": selected_calendar,
            "schedules": schedules,
            "selected_schedule": selected_schedule,
            "working_intervals": working_intervals,
            "exceptions": exceptions,
            "selected_exception": selected_exception,
            "exception_intervals": exception_intervals,
            "workflows": workflows,
            "selected_workflow": selected_workflow,
            "steps": steps,
            "selected_step": selected_step,
            "selected_sla": selected_sla,
            "calendar_form": calendar_form,
            "schedule_form": schedule_form,
            "interval_form": interval_form,
            "bulk_form": bulk_form,
            "exception_form": exception_form,
            "exception_interval_form": exception_interval_form,
            "sla_form": sla_form,
        },
    )
