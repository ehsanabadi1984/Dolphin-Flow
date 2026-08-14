from datetime import date, time

from django.core.exceptions import ValidationError
from django.test import TestCase

from workflow.models import (
    BusinessCalendar,
    WeeklySchedule,
    WorkingInterval,
    CalendarException,
    CalendarExceptionInterval,
)


class CalendarModelTests(TestCase):

    def setUp(self):
        self.calendar = BusinessCalendar.objects.create(
            name="Default Business Calendar",
            timezone="Asia/Tehran",
            is_active=True,
        )

    # ---------------------------------------------------------
    # BusinessCalendar
    # ---------------------------------------------------------

    def test_business_calendar_can_be_created(self):
        self.assertEqual(
            self.calendar.name,
            "Default Business Calendar",
        )

        self.assertEqual(
            self.calendar.timezone,
            "Asia/Tehran",
        )

        self.assertTrue(self.calendar.is_active)

    # ---------------------------------------------------------
    # WeeklySchedule
    # ---------------------------------------------------------

    def test_weekly_schedule_can_be_created(self):
        schedule = WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=WeeklySchedule.Weekday.SATURDAY,
            is_working=True,
        )

        self.assertEqual(
            schedule.calendar,
            self.calendar,
        )

        self.assertTrue(schedule.is_working)

    def test_calendar_cannot_have_duplicate_weekday_schedule(self):
        WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=WeeklySchedule.Weekday.SATURDAY,
            is_working=True,
        )

        with self.assertRaises(Exception):
            WeeklySchedule.objects.create(
                calendar=self.calendar,
                weekday=WeeklySchedule.Weekday.SATURDAY,
                is_working=False,
            )

    # ---------------------------------------------------------
    # WorkingInterval
    # ---------------------------------------------------------

    def test_working_interval_can_be_created(self):
        schedule = WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=WeeklySchedule.Weekday.SATURDAY,
            is_working=True,
        )

        interval = WorkingInterval(
            weekly_schedule=schedule,
            start_time=time(8, 0),
            end_time=time(13, 0),
        )

        interval.full_clean()
        interval.save()

        self.assertEqual(
            interval.start_time,
            time(8, 0),
        )

        self.assertEqual(
            interval.end_time,
            time(13, 0),
        )

    def test_working_interval_rejects_invalid_time_range(self):
        schedule = WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=WeeklySchedule.Weekday.SATURDAY,
            is_working=True,
        )

        interval = WorkingInterval(
            weekly_schedule=schedule,
            start_time=time(13, 0),
            end_time=time(8, 0),
        )

        with self.assertRaises(ValidationError):
            interval.full_clean()

    def test_working_interval_rejects_equal_start_and_end(self):
        schedule = WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=WeeklySchedule.Weekday.SATURDAY,
            is_working=True,
        )

        interval = WorkingInterval(
            weekly_schedule=schedule,
            start_time=time(8, 0),
            end_time=time(8, 0),
        )

        with self.assertRaises(ValidationError):
            interval.full_clean()

    def test_adjacent_working_intervals_are_allowed(self):
        schedule = WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=WeeklySchedule.Weekday.SATURDAY,
            is_working=True,
        )

        first = WorkingInterval(
            weekly_schedule=schedule,
            start_time=time(8, 0),
            end_time=time(13, 0),
        )
        first.full_clean()
        first.save()

        second = WorkingInterval(
            weekly_schedule=schedule,
            start_time=time(13, 0),
            end_time=time(16, 30),
        )
        second.full_clean()
        second.save()

        self.assertEqual(
            WorkingInterval.objects.filter(
                weekly_schedule=schedule,
            ).count(),
            2,
        )

    def test_overlapping_working_intervals_are_rejected(self):
        schedule = WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=WeeklySchedule.Weekday.SATURDAY,
            is_working=True,
        )

        first = WorkingInterval(
            weekly_schedule=schedule,
            start_time=time(8, 0),
            end_time=time(13, 0),
        )
        first.full_clean()
        first.save()

        overlapping = WorkingInterval(
            weekly_schedule=schedule,
            start_time=time(12, 0),
            end_time=time(16, 30),
        )

        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    # ---------------------------------------------------------
    # CalendarException
    # ---------------------------------------------------------

    def test_non_working_calendar_exception_can_be_created(self):
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 21),
            status=CalendarException.Status.NON_WORKING,
            title="تعطیلی رسمی",
        )

        self.assertEqual(
            exception.status,
            CalendarException.Status.NON_WORKING,
        )

    def test_working_calendar_exception_can_be_created(self):
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 22),
            status=CalendarException.Status.WORKING,
            title="روز کاری فوق‌العاده",
        )

        self.assertEqual(
            exception.status,
            CalendarException.Status.WORKING,
        )

    def test_calendar_cannot_have_duplicate_exception_for_same_date(self):
        CalendarException.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 21),
            status=CalendarException.Status.NON_WORKING,
        )

        with self.assertRaises(Exception):
            CalendarException.objects.create(
                calendar=self.calendar,
                date=date(2026, 8, 21),
                status=CalendarException.Status.WORKING,
            )

    # ---------------------------------------------------------
    # CalendarExceptionInterval
    # ---------------------------------------------------------

    def test_working_exception_interval_can_be_created(self):
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 22),
            status=CalendarException.Status.WORKING,
        )

        interval = CalendarExceptionInterval(
            exception=exception,
            start_time=time(8, 0),
            end_time=time(13, 0),
        )

        interval.full_clean()
        interval.save()

        self.assertEqual(
            interval.exception,
            exception,
        )

    def test_exception_interval_rejects_invalid_time_range(self):
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 22),
            status=CalendarException.Status.WORKING,
        )

        interval = CalendarExceptionInterval(
            exception=exception,
            start_time=time(13, 0),
            end_time=time(8, 0),
        )

        with self.assertRaises(ValidationError):
            interval.full_clean()

    def test_exception_interval_is_not_allowed_for_non_working_exception(self):
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 21),
            status=CalendarException.Status.NON_WORKING,
        )

        interval = CalendarExceptionInterval(
            exception=exception,
            start_time=time(8, 0),
            end_time=time(13, 0),
        )

        with self.assertRaises(ValidationError):
            interval.full_clean()

    def test_adjacent_exception_intervals_are_allowed(self):
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 22),
            status=CalendarException.Status.WORKING,
        )

        first = CalendarExceptionInterval(
            exception=exception,
            start_time=time(8, 0),
            end_time=time(13, 0),
        )
        first.full_clean()
        first.save()

        second = CalendarExceptionInterval(
            exception=exception,
            start_time=time(13, 0),
            end_time=time(16, 30),
        )
        second.full_clean()
        second.save()

        self.assertEqual(
            CalendarExceptionInterval.objects.filter(
                exception=exception,
            ).count(),
            2,
        )

    def test_overlapping_exception_intervals_are_rejected(self):
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 22),
            status=CalendarException.Status.WORKING,
        )

        first = CalendarExceptionInterval(
            exception=exception,
            start_time=time(8, 0),
            end_time=time(13, 0),
        )
        first.full_clean()
        first.save()

        overlapping = CalendarExceptionInterval(
            exception=exception,
            start_time=time(12, 0),
            end_time=time(16, 30),
        )

        with self.assertRaises(ValidationError):
            overlapping.full_clean()