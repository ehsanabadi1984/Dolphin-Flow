"""Celery task base that prevents new tasks from starting during restore."""
from celery import Task
from celery.exceptions import Ignore

from .restore_maintenance import maintenance_is_active


class RestoreMaintenanceAwareTask(Task):
    """Reject task execution while the persistent restore gate is active."""

    abstract = True

    @staticmethod
    def _reject_during_maintenance():
        if maintenance_is_active():
            raise Ignore("Restore maintenance is active; task was not started.")

    def before_start(self, task_id, args, kwargs):
        # Celery's worker tracer invokes this hook before Task.run().
        self._reject_during_maintenance()
        return super().before_start(task_id, args, kwargs)

    def __call__(self, *args, **kwargs):
        # Keep direct/eager invocation protected as well.
        self._reject_during_maintenance()
        return super().__call__(*args, **kwargs)
