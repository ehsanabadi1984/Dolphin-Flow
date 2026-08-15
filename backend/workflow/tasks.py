from celery import shared_task

from .sla_monitor_services import SLAMonitorService


@shared_task
def process_sla_monitor():
    return SLAMonitorService.process_active_slas()