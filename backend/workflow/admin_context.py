from collections import OrderedDict

from .admin import (
    ADMIN_CATEGORIES,
    build_admin_structure,
)
from .branding_models import SystemBranding


def dolphin_flow_admin_context(request):

    return {
        "admin_categories": ADMIN_CATEGORIES,
        "admin_structure": build_admin_structure(request),
        "system_branding": SystemBranding.get_current(),
    }
