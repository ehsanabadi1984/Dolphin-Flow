from django.http import HttpResponse

from .restore_maintenance import RestoreMaintenanceError
from .restore_drain import acquire_application_work_lease


class RestoreMaintenanceMiddleware:
    """Hold a shared drain lease for each in-flight HTTP request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            lease = acquire_application_work_lease(timeout=0)
        except RestoreMaintenanceError:
            return HttpResponse(
                "سامانه موقتاً برای عملیات بازیابی در دسترس نیست. لطفاً کمی بعد مراجعه کنید.",
                status=503,
                content_type="text/plain; charset=utf-8",
                headers={"Retry-After": "60"},
            )

        try:
            response = self.get_response(request)
        except Exception:
            lease.release()
            raise

        if getattr(response, "streaming", False):
            # Django closes streaming responses after their iterator completes.
            response._resource_closers.append(lease.release)
        else:
            lease.release()
        return response
