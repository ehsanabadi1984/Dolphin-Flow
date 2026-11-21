"""Celery task base that prevents new tasks from starting during restore."""
from celery import Task
from celery.exceptions import Ignore

from .restore_maintenance import maintenance_is_active


class RestoreMaintenanceAwareTask(Task):
    """Reject task execution while the persistent restore gate is active."""

    abstract = True

    def __call__(self, *args, **kwargs):
        if maintenance_is_active():
            raise Ignore("Restore maintenance is active; task was not started.")
        return super().__call__(*args, **kwargs)
