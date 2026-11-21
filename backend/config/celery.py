import os

from celery import Celery


os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "config.settings",
)

app = Celery(
    "dolphin_flow",
)

app.config_from_object(
    "django.conf:settings",
    namespace="CELERY",
)

from backup.restore_maintenance_tasks import RestoreMaintenanceAwareTask

app.Task = RestoreMaintenanceAwareTask

app.autodiscover_tasks()
