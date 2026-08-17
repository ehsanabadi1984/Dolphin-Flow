from .admin import ADMIN_CATEGORIES


def dolphin_flow_admin_context(request):
    return {
        "admin_categories": ADMIN_CATEGORIES,
    }