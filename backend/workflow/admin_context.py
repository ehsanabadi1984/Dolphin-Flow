from collections import OrderedDict

from .admin import (
    ADMIN_CATEGORIES,
    build_admin_structure,
)


def dolphin_flow_admin_context(request):

    return {
        "admin_categories": ADMIN_CATEGORIES,
        "admin_structure": build_admin_structure(request),
    }