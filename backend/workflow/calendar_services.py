from dataclasses import dataclass
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta

from django.utils import timezone

from workflow.models import (
    BusinessCalendar,
    CalendarException,
    WeeklySchedule,
)


@dataclass(frozen=True)
class _WorkingInterval:
    start_time: object
    end_time: object


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

        # A non-working exception closes the entire date, regardless of
        # the regular weekly schedule.
        if (
            exception is not None
            and exception.status == CalendarException.Status.NON_WORKING
        ):
            return []

        intervals = []

        # A WORKING exception adds intervals to the regular schedule.
        # If the weekday is normally non-working, this naturally leaves
        # only the exception intervals.
        schedule = (
            calendar.weekly_schedules
            .filter(
                weekday=value.weekday(),
                is_working=True,
            )
            .prefetch_related("intervals")
            .first()
        )

        if schedule is not None:
            intervals.extend(
                (item.start_time, item.end_time)
                for item in schedule.intervals.all()
            )

        if (
            exception is not None
            and exception.status == CalendarException.Status.WORKING
        ):
            intervals.extend(
                (item.start_time, item.end_time)
                for item in exception.intervals.all()
            )

        # Sort and merge overlapping or directly adjacent intervals. This
        # is important because an exception can overlap the regular schedule.
        intervals.sort(key=lambda item: (item[0], item[1]))
        merged = []

        for interval_start, interval_end in intervals:
            if merged and interval_start <= merged[-1][1]:
                previous_start, previous_end = merged[-1]
                merged[-1] = (
                    previous_start,
                    max(previous_end, interval_end),
                )
            else:
                merged.append((interval_start, interval_end))

        return [
            _WorkingInterval(start_time=start, end_time=end)
            for start, end in merged
        ]

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
        calendar_tz = ZoneInfo(calendar.timezone)

        if timezone.is_naive(start):
            start_local = timezone.make_aware(start, calendar_tz)
        else:
            start_local = start.astimezone(calendar_tz)

        if timezone.is_naive(end):
            end_local = timezone.make_aware(end, calendar_tz)
        else:
            end_local = end.astimezone(calendar_tz)

        if start_local >= end_local:
            return timedelta(0)

        total = timedelta(0)
        current_date = start_local.date()
        end_date = end_local.date()

        while current_date <= end_date:
            intervals = CalendarService.get_working_intervals(
                calendar=calendar,
                value=current_date,
            )

            for interval in intervals:
                interval_start_dt = timezone.make_aware(
                    datetime.combine(current_date, interval.start_time),
                    calendar_tz,
                )
                interval_end_dt = timezone.make_aware(
                    datetime.combine(current_date, interval.end_time),
                    calendar_tz,
                )

                effective_start = max(start_local, interval_start_dt)
                effective_end = min(end_local, interval_end_dt)

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
