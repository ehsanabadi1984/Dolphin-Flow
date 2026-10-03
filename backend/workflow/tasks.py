from celery import shared_task

from .sla_monitor_services import SLAMonitorService
from .n8n_notification_services import N8NNotificationDispatcher


@shared_task
def process_sla_monitor():
    return SLAMonitorService.process_active_slas()

@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def dispatch_n8n_notification(notification_id):
    return N8NNotificationDispatcher.dispatch(notification_id)
