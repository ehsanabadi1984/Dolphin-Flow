"""Celery task base that participates in the restore drain protocol."""
import threading

from celery import Task
from celery.exceptions import Ignore

from .restore_maintenance import RestoreMaintenanceError
from .restore_drain import acquire_application_work_lease


_leases_lock = threading.Lock()
_worker_leases = {}


class RestoreMaintenanceAwareTask(Task):
    """Hold shared drain ownership for the complete lifetime of worker tasks."""

    abstract = True

    def before_start(self, task_id, args, kwargs):
        try:
            lease = acquire_application_work_lease(timeout=0)
        except RestoreMaintenanceError as exc:
            raise Ignore(str(exc)) from exc

        key = (id(self), task_id)
        with _leases_lock:
            if key in _worker_leases:
                lease.release()
                raise Ignore("Duplicate Celery task drain lease.")
            _worker_leases[key] = lease

        try:
            return super().before_start(task_id, args, kwargs)
        except Exception:
            with _leases_lock:
                held = _worker_leases.pop(key, None)
            if held:
                held.release()
            raise

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        key = (id(self), task_id)
        with _leases_lock:
            lease = _worker_leases.pop(key, None)
        try:
            return super().after_return(status, retval, task_id, args, kwargs, einfo)
        finally:
            if lease:
                lease.release()

    def __call__(self, *args, **kwargs):
        # Direct/eager invocation does not necessarily pass through worker hooks.
        try:
            lease = acquire_application_work_lease(timeout=0)
        except RestoreMaintenanceError as exc:
            raise Ignore(str(exc)) from exc
        try:
            return super().__call__(*args, **kwargs)
        finally:
            lease.release()
