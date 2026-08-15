from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from django.utils import timezone

from workflow.models import (
    BusinessCalendar,
    CalendarException,
    WeeklySchedule,
)


class CalendarService:

    @staticmethod
    def get_working_intervals(
        *,
        calendar: BusinessCalendar,
        value,
    ):
        exception = (
            calendar.exceptions
            .filter(date=value)
            .prefetch_related("intervals")
            .first()
        )

        if exception is not None:

            if (
                exception.status
                == CalendarException.Status.NON_WORKING
            ):
                return []

            return list(
                exception.intervals.all()
            )

        weekday = value.weekday()

        schedule = (
            calendar.weekly_schedules
            .filter(
                weekday=weekday,
                is_working=True,
            )
            .prefetch_related("intervals")
            .first()
        )

        if schedule is None:
            return []

        return list(
            schedule.intervals.all()
        )

    @staticmethod
    def is_working_datetime(
        *,
        calendar: BusinessCalendar,
        value,
    ):
        calendar_timezone = ZoneInfo(
            calendar.timezone
        )

        local_value = timezone.localtime(
            value,
            calendar_timezone,
        )

        intervals = CalendarService.get_working_intervals(
            calendar=calendar,
            value=local_value.date(),
        )

        current_time = local_value.time()

        for interval in intervals:
            if (
                interval.start_time
                <= current_time
                < interval.end_time
            ):
                return True

        return False

    @staticmethod
    def add_working_duration(
        *,
        calendar,
        start,
        duration,
    ):
        """
        Add a working duration to a datetime according to the
        calendar's weekly schedule and date exceptions.

        The returned datetime uses the calendar timezone.
        """

        if duration < timedelta(0):
            raise ValueError(
                "duration cannot be negative."
            )

        calendar_tz = ZoneInfo(calendar.timezone)

        if timezone.is_naive(start):
            current = timezone.make_aware(
                start,
                calendar_tz,
            )
        else:
            current = start.astimezone(calendar_tz)

        if duration == timedelta(0):
            return current

        remaining = duration

        while remaining > timedelta(0):
            current_date = current.date()
            current_time = current.time()

            intervals = CalendarService.get_working_intervals(
                calendar=calendar,
                value=current_date,
            )

            moved_to_interval = False

            for interval in intervals:
                start_time = interval.start_time
                end_time = interval.end_time

                # Current time is before this working interval.
                if current_time < start_time:
                    current = timezone.make_aware(
                        datetime.combine(
                            current_date,
                            start_time,
                        ),
                        calendar_tz,
                    )

                    current_time = start_time

                # Current time is at or after the end of this interval.
                if current_time >= end_time:
                    continue

                moved_to_interval = True

                interval_end = timezone.make_aware(
                    datetime.combine(
                        current_date,
                        end_time,
                    ),
                    calendar_tz,
                )

                available = interval_end - current

                if remaining <= available:
                    return current + remaining

                remaining -= available
                current = interval_end
                current_time = end_time

            if moved_to_interval:
                # We consumed the remainder of this day's working
                # intervals and still have duration left.
                current = timezone.make_aware(
                    datetime.combine(
                        current_date + timedelta(days=1),
                        datetime.min.time(),
                    ),
                    calendar_tz,
                )
            else:
                # No working interval remains for this date.
                current = timezone.make_aware(
                    datetime.combine(
                        current_date + timedelta(days=1),
                        datetime.min.time(),
                    ),
                    calendar_tz,
                )

        return current

    @staticmethod
    def working_duration_between(
        *,
        calendar,
        start,
        end,
    ):
        if start >= end:
            return timedelta(0)

        total = timedelta(0)
        current_date = start.date()
        end_date = end.date()

        while current_date <= end_date:
            intervals = CalendarService.get_working_intervals(
                calendar=calendar,
                date=current_date,
            )

            for interval_start, interval_end in intervals:
                interval_start_dt = datetime.combine(
                    current_date,
                    interval_start,
                    tzinfo=start.tzinfo,
                )
                interval_end_dt = datetime.combine(
                    current_date,
                    interval_end,
                    tzinfo=start.tzinfo,
                )

                effective_start = max(start, interval_start_dt)
                effective_end = min(end, interval_end_dt)

                if effective_start < effective_end:
                    total += effective_end - effective_start

            current_date += timedelta(days=1)

        return total

    @staticmethod
    def subtract_working_duration(
        *,
        calendar,
        end,
        duration,
    ):
        """
        Subtract a working duration from a datetime according to the
        calendar's weekly schedule and date exceptions.

        The returned datetime uses the calendar timezone.
        """

        if duration < timedelta(0):
            raise ValueError(
                "duration cannot be negative."
            )

        calendar_tz = ZoneInfo(calendar.timezone)

        if timezone.is_naive(end):
            current = timezone.make_aware(
                end,
                calendar_tz,
            )
        else:
            current = end.astimezone(calendar_tz)

        if duration == timedelta(0):
            return current

        remaining = duration

        while remaining > timedelta(0):
            current_date = current.date()
            current_time = current.time()

            intervals = CalendarService.get_working_intervals(
                calendar=calendar,
                value=current_date,
            )

            moved_to_interval = False

            for interval in reversed(intervals):
                start_time = interval.start_time
                end_time = interval.end_time

                # Current time is after this interval.
                if current_time > end_time:
                    interval_end = timezone.make_aware(
                        datetime.combine(
                            current_date,
                            end_time,
                        ),
                        calendar_tz,
                    )
                elif current_time > start_time:
                    interval_end = current
                else:
                    continue

                interval_start = timezone.make_aware(
                    datetime.combine(
                        current_date,
                        start_time,
                    ),
                    calendar_tz,
                )

                available = interval_end - interval_start

                if available <= timedelta(0):
                    continue

                moved_to_interval = True

                if remaining <= available:
                    return interval_end - remaining

                remaining -= available
                current = interval_start
                current_time = start_time

            # No remaining working interval today.
            current = timezone.make_aware(
                datetime.combine(
                    current_date - timedelta(days=1),
                    datetime.max.time(),
                ),
                calendar_tz,
            )

        return current
