import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .sla_monitor_services import SLAMonitorService

logger = logging.getLogger(__name__)


@shared_task
def process_sla_monitor():
    return SLAMonitorService.process_active_slas()


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True)
def dispatch_sms_notification(self, notification_id):
    from .models import SMSDelivery
    from .sms_services import SMSDispatcher

    try:
        return SMSDispatcher.dispatch(notification_id)
    except Exception as exc:
        delivery = SMSDelivery.objects.filter(notification_id=notification_id).first()
        if delivery and delivery.status in (SMSDelivery.Status.PENDING, SMSDelivery.Status.SENDING):
            delivery.status = SMSDelivery.Status.FAILED
            delivery.last_error = str(exc)[:4000]
            delivery.save(update_fields=("status", "last_error", "updated_at"))
        logger.exception(
            "SMS delivery failed without automatic resend for notification %s",
            notification_id,
        )
        return SMSDelivery.Status.FAILED


@shared_task
def reconcile_stale_sms_deliveries():
    """Mark abandoned in-flight sends UNKNOWN; never resubmit them automatically."""
    from .models import SMSDelivery

    stale_after = max(60, settings.SMS_DELIVERY_STALE_AFTER)
    cutoff = timezone.now() - timedelta(seconds=stale_after)
    return SMSDelivery.objects.filter(
        status=SMSDelivery.Status.SENDING,
        updated_at__lt=cutoff,
    ).update(
        status=SMSDelivery.Status.UNKNOWN,
        last_error="Worker did not record a final result before the delivery timeout.",
        updated_at=timezone.now(),
    )


@shared_task
def requeue_pending_sms_deliveries():
    """Recover outbox rows that could not be enqueued after notification commit."""
    from .models import SMSDelivery

    delay = max(30, settings.SMS_PENDING_REQUEUE_AFTER)
    cutoff = timezone.now() - timedelta(seconds=delay)
    pending_ids = list(
        SMSDelivery.objects.filter(
            status=SMSDelivery.Status.PENDING,
            updated_at__lt=cutoff,
        ).order_by("created_at").values_list("notification_id", flat=True)[:100]
    )
    queued = 0
    for notification_id in pending_ids:
        try:
            dispatch_sms_notification.delay(notification_id)
            queued += 1
        except Exception:
            logger.exception("Unable to requeue SMS for notification %s", notification_id)
    return queued
