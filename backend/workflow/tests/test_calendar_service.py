from datetime import date, datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from workflow.models import (
    BusinessCalendar,
    WeeklySchedule,
    WorkingInterval,
    CalendarException,
    CalendarExceptionInterval,
)
from workflow.calendar_services import CalendarService


class CalendarServiceTests(TestCase):

    def setUp(self):
        self.calendar = BusinessCalendar.objects.create(
            name="Test Calendar",
            timezone="Asia/Tehran",
            is_active=True,
        )

        self._create_weekly_schedule(
            WeeklySchedule.Weekday.SATURDAY,
            True,
            [
                (time(8, 0), time(13, 0)),
                (time(13, 30), time(16, 30)),
            ],
        )

        self._create_weekly_schedule(
            WeeklySchedule.Weekday.SUNDAY,
            True,
            [
                (time(8, 0), time(13, 0)),
                (time(13, 30), time(16, 30)),
            ],
        )

        self._create_weekly_schedule(
            WeeklySchedule.Weekday.MONDAY,
            True,
            [
                (time(8, 0), time(13, 0)),
                (time(13, 30), time(16, 30)),
            ],
        )

        self._create_weekly_schedule(
            WeeklySchedule.Weekday.TUESDAY,
            True,
            [
                (time(8, 0), time(13, 0)),
                (time(13, 30), time(16, 30)),
            ],
        )

        self._create_weekly_schedule(
            WeeklySchedule.Weekday.WEDNESDAY,
            True,
            [
                (time(8, 0), time(13, 0)),
                (time(13, 30), time(16, 30)),
            ],
        )

        self._create_weekly_schedule(
            WeeklySchedule.Weekday.THURSDAY,
            False,
            [],
        )

        self._create_weekly_schedule(
            WeeklySchedule.Weekday.FRIDAY,
            False,
            [],
        )

    def _create_weekly_schedule(
        self,
        weekday,
        is_working,
        intervals,
    ):
        schedule = WeeklySchedule.objects.create(
            calendar=self.calendar,
            weekday=weekday,
            is_working=is_working,
        )

        for start_time, end_time in intervals:
            WorkingInterval.objects.create(
                weekly_schedule=schedule,
                start_time=start_time,
                end_time=end_time,
            )

        return schedule

    def test_working_datetime_inside_interval(self):
        dt = timezone.make_aware(
            datetime(2026, 8, 15, 10, 0)
        )

        self.assertTrue(
            CalendarService.is_working_datetime(
                calendar=self.calendar,
                value=dt,
            )
        )

    def test_working_datetime_at_interval_start(self):
        dt = timezone.make_aware(
            datetime(2026, 8, 15, 8, 0)
        )

        self.assertTrue(
            CalendarService.is_working_datetime(
                calendar=self.calendar,
                value=dt,
            )
        )

    def test_working_datetime_at_second_interval_start(self):
        dt = timezone.make_aware(
            datetime(2026, 8, 15, 13, 30)
        )

        self.assertTrue(
            CalendarService.is_working_datetime(
                calendar=self.calendar,
                value=dt,
            )
        )

    def test_working_datetime_at_interval_end(self):
        dt = timezone.make_aware(
            datetime(2026, 8, 15, 13, 0)
        )

        intervals = CalendarService.get_working_intervals(
            calendar=self.calendar,
            value=dt.date(),
        )

        self.assertFalse(
            CalendarService.is_working_datetime(
                calendar=self.calendar,
                value=dt,
            )
        )

    def test_working_datetime_at_working_day_end(self):
        dt = timezone.make_aware(
            datetime(2026, 8, 15, 16, 30)
        )

        self.assertFalse(
            CalendarService.is_working_datetime(
                calendar=self.calendar,
                value=dt,
            )
        )

    def test_non_working_weekday(self):
        dt = timezone.make_aware(
            datetime(2026, 8, 14, 10, 0)
        )

        self.assertFalse(
            CalendarService.is_working_datetime(
                calendar=self.calendar,
                value=dt,
            )
        )

    def test_get_working_intervals(self):
        intervals = CalendarService.get_working_intervals(
            calendar=self.calendar,
            value=date(2026, 8, 15),
        )

        self.assertEqual(len(intervals), 2)

        self.assertEqual(
            intervals[0].start_time,
            time(8, 0),
        )

        self.assertEqual(
            intervals[0].end_time,
            time(13, 0),
        )

        self.assertEqual(
            intervals[1].start_time,
            time(13, 30),
        )

        self.assertEqual(
            intervals[1].end_time,
            time(16, 30),
        )

    def test_get_empty_intervals_for_non_working_day(self):
        intervals = CalendarService.get_working_intervals(
            calendar=self.calendar,
            value=date(2026, 8, 14),
        )

        self.assertEqual(intervals, [])

    def test_non_working_exception_overrides_schedule(self):
        test_date = date(2026, 8, 15)

        CalendarException.objects.create(
            calendar=self.calendar,
            date=test_date,
            status=CalendarException.Status.NON_WORKING,
            title="Test Holiday",
        )

        intervals = CalendarService.get_working_intervals(
            calendar=self.calendar,
            value=test_date,
        )

        self.assertEqual(intervals, [])

    def test_working_exception_overrides_non_working_weekday(self):
        test_date = date(2026, 8, 14)

        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=test_date,
            status=CalendarException.Status.WORKING,
            title="Special Working Day",
        )

        CalendarExceptionInterval.objects.create(
            exception=exception,
            start_time=time(9, 0),
            end_time=time(12, 0),
        )

        intervals = CalendarService.get_working_intervals(
            calendar=self.calendar,
            value=test_date,
        )

        self.assertEqual(len(intervals), 1)

        self.assertEqual(
            intervals[0].start_time,
            time(9, 0),
        )

        self.assertEqual(
            intervals[0].end_time,
            time(12, 0),
        )

    def test_working_exception_adds_intervals_to_regular_working_day(self):
        test_date = date(2026, 8, 15)  # Saturday: normally 08:00-13:00, 13:30-16:30.
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=test_date,
            status=CalendarException.Status.WORKING,
            title="Extended working day",
        )
        CalendarExceptionInterval.objects.create(
            exception=exception,
            start_time=time(17, 0),
            end_time=time(19, 0),
        )

        intervals = CalendarService.get_working_intervals(
            calendar=self.calendar,
            value=test_date,
        )

        self.assertEqual(
            [(item.start_time, item.end_time) for item in intervals],
            [
                (time(8, 0), time(13, 0)),
                (time(13, 30), time(16, 30)),
                (time(17, 0), time(19, 0)),
            ],
        )

    def test_working_exception_merges_overlapping_and_adjacent_intervals(self):
        test_date = date(2026, 8, 15)
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=test_date,
            status=CalendarException.Status.WORKING,
            title="Adjusted working hours",
        )
        # This interval overlaps the first regular interval and bridges
        # the lunch gap; the union therefore becomes one continuous interval.
        CalendarExceptionInterval.objects.create(
            exception=exception,
            start_time=time(12, 0),
            end_time=time(14, 0),
        )
        # Directly adjacent to the end of the regular afternoon interval.
        CalendarExceptionInterval.objects.create(
            exception=exception,
            start_time=time(16, 30),
            end_time=time(17, 0),
        )

        intervals = CalendarService.get_working_intervals(
            calendar=self.calendar,
            value=test_date,
        )

        self.assertEqual(
            [(item.start_time, item.end_time) for item in intervals],
            [(time(8, 0), time(17, 0))],
        )

    def test_working_duration_between_uses_combined_exception_intervals(self):
        test_date = date(2026, 8, 15)
        exception = CalendarException.objects.create(
            calendar=self.calendar,
            date=test_date,
            status=CalendarException.Status.WORKING,
            title="Extended working day",
        )
        CalendarExceptionInterval.objects.create(
            exception=exception,
            start_time=time(17, 0),
            end_time=time(19, 0),
        )

        start = timezone.make_aware(datetime(2026, 8, 15, 8, 0))
        end = timezone.make_aware(datetime(2026, 8, 15, 19, 0))

        duration = CalendarService.working_duration_between(
            calendar=self.calendar,
            start=start,
            end=end,
        )

        self.assertEqual(duration, timedelta(hours=10))

    def test_add_working_duration_inside_interval(self):
        start = timezone.make_aware(
            datetime(2026, 8, 15, 10, 0)
        )

        result = CalendarService.add_working_duration(
            calendar=self.calendar,
            start=start,
            duration=timedelta(hours=2),
        )

        self.assertEqual(
            result,
            timezone.make_aware(
                datetime(2026, 8, 15, 12, 0)
            ),
        )

    def test_add_working_duration_crosses_lunch_break(self):
        start = timezone.make_aware(
            datetime(2026, 8, 15, 12, 0)
        )

        result = CalendarService.add_working_duration(
            calendar=self.calendar,
            start=start,
            duration=timedelta(hours=2),
        )

        self.assertEqual(
            result,
            timezone.make_aware(
                datetime(2026, 8, 15, 14, 30)
            ),
        )

    def test_add_working_duration_crosses_working_day_end(self):
        start = timezone.make_aware(
            datetime(2026, 8, 15, 15, 30)
        )

        result = CalendarService.add_working_duration(
            calendar=self.calendar,
            start=start,
            duration=timedelta(hours=2),
        )

        self.assertEqual(
            result,
            timezone.make_aware(
                datetime(2026, 8, 16, 9, 0)
            ),
        )

    def test_add_working_duration_skips_non_working_weekdays(self):
        start = timezone.make_aware(
            datetime(2026, 8, 20, 10, 0)
        )

        result = CalendarService.add_working_duration(
            calendar=self.calendar,
            start=start,
            duration=timedelta(hours=2),
        )

        self.assertEqual(
            result,
            timezone.make_aware(
                datetime(2026, 8, 22, 10, 0)
            ),
        )

    def test_add_working_duration_starts_from_next_working_interval(self): 
        start = timezone.make_aware(
            datetime(2026, 8, 15, 13, 0)
        )

        result = CalendarService.add_working_duration(
            calendar=self.calendar,
            start=start,
            duration=timedelta(hours=1),
        )

        self.assertEqual(
            result,
            timezone.make_aware(
                datetime(2026, 8, 15, 14, 30)
            ),
        )

    def test_add_working_duration_starts_on_non_working_day(self):
        start = timezone.make_aware(
            datetime(2026, 8, 20, 10, 0)
        )

        result = CalendarService.add_working_duration(
            calendar=self.calendar,
            start=start,
            duration=timedelta(hours=1),
        )

        self.assertEqual(
            result,
            timezone.make_aware(
                datetime(2026, 8, 22, 9, 0)
            ),
        )