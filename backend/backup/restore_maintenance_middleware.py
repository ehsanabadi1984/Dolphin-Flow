from django.http import HttpResponse


class RestoreMaintenanceMiddleware:
    """Block new HTTP requests while a restore cutover owns the maintenance gate."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .restore_maintenance import maintenance_is_active

        if maintenance_is_active():
            return HttpResponse(
                "سامانه موقتاً برای عملیات بازیابی در دسترس نیست. لطفاً کمی بعد مراجعه کنید.",
                status=503,
                content_type="text/plain; charset=utf-8",
                headers={"Retry-After": "60"},
            )
        return self.get_response(request)
