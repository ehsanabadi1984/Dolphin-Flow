from .models import UserPreference


class UserSessionTimeoutMiddleware:
    """Apply each user's idle session timeout to their authenticated session."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            preference, _ = UserPreference.objects.get_or_create(
                user=request.user,
            )
            request.session.set_expiry(preference.session_timeout)

        return self.get_response(request)
