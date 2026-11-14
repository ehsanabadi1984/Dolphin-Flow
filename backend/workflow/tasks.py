import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.db.models import Q

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
        if delivery and delivery.status == SMSDelivery.Status.SENDING:
            # The provider may have accepted the request before an unexpected
            # exception occurred. Never make this row eligible for a resend.
            delivery.status = SMSDelivery.Status.UNKNOWN
            delivery.last_error = str(exc)[:4000]
            delivery.save(update_fields=("status", "last_error", "updated_at"))
            result_status = SMSDelivery.Status.UNKNOWN
        elif delivery and delivery.status == SMSDelivery.Status.PENDING:
            # No send was claimed; this is a definitive pre-submission failure.
            delivery.status = SMSDelivery.Status.FAILED
            delivery.last_error = str(exc)[:4000]
            delivery.save(update_fields=("status", "last_error", "updated_at"))
            result_status = SMSDelivery.Status.FAILED
        else:
            result_status = delivery.status if delivery else SMSDelivery.Status.FAILED
        logger.exception(
            "SMS delivery task failed for notification %s",
            notification_id,
        )
        return result_status


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
    """Recover pending outbox rows without repeatedly enqueueing the same row."""
    from .models import SMSDelivery
    from .sms_services import enqueue_pending_sms_notification

    delay = max(60, settings.SMS_PENDING_REQUEUE_AFTER)
    cutoff = timezone.now() - timedelta(seconds=delay)
    pending_ids = list(
        SMSDelivery.objects.filter(
            status=SMSDelivery.Status.PENDING,
        ).filter(
            Q(last_queued_at__isnull=True) | Q(last_queued_at__lt=cutoff)
        ).order_by("created_at").values_list("notification_id", flat=True)[:100]
    )
    queued = 0
    for notification_id in pending_ids:
        try:
            if enqueue_pending_sms_notification(
                notification_id, min_interval_seconds=delay,
            ):
                queued += 1
        except Exception:
            logger.exception("Unable to requeue SMS for notification %s", notification_id)
    return queued
