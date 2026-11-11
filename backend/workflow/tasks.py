import logging

from celery import shared_task

from .sla_monitor_services import SLAMonitorService

logger = logging.getLogger(__name__)


@shared_task
def process_sla_monitor():
    return SLAMonitorService.process_active_slas()


@shared_task(bind=True, max_retries=5, acks_late=True, reject_on_worker_lost=True)
def dispatch_sms_notification(self, notification_id):
    from .models import SMSDelivery
    from .sms_services import SMSDispatcher

    try:
        return SMSDispatcher.dispatch(notification_id)
    except Exception as exc:
        delivery = SMSDelivery.objects.filter(
            notification_id=notification_id
        ).first()
        if delivery:
            delivery.last_error = str(exc)[:4000]
            if self.request.retries >= self.max_retries:
                delivery.status = SMSDelivery.Status.FAILED
            delivery.save(update_fields=("last_error", "status", "updated_at"))

        if self.request.retries >= self.max_retries:
            logger.exception(
                "SMS delivery permanently failed for notification %s",
                notification_id,
            )
            raise

        raise self.retry(
            exc=exc,
            countdown=min(60 * (2 ** self.request.retries), 900),
        )
