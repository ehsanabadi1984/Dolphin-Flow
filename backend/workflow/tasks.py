from celery import shared_task

from .sla_monitor_services import SLAMonitorService
from .n8n_notification_services import N8NNotificationDispatcher


@shared_task
def process_sla_monitor():
    return SLAMonitorService.process_active_slas()