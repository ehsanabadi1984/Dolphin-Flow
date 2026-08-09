"""
URL configuration for config project.
"""

from django.contrib import admin
from django.urls import include, path

from workflow.admin import (
    workflow_dynamic_steps,
    workflow_dynamic_transitions,
)


urlpatterns = [
    # ---------------------------------------------------------
    # Workflow Dynamic Select Endpoints
    # ---------------------------------------------------------

    path(
        "admin/workflow/dynamic/steps/",
        admin.site.admin_view(workflow_dynamic_steps),
        name="workflow_dynamic_steps",
    ),

    path(
        "admin/workflow/dynamic/transitions/",
        admin.site.admin_view(workflow_dynamic_transitions),
        name="workflow_dynamic_transitions",
    ),

    # ---------------------------------------------------------
    # Django Admin
    # ---------------------------------------------------------

    path(
        "admin/",
        admin.site.urls,
    ),

    # ---------------------------------------------------------
    # Accounts
    # ---------------------------------------------------------

    path(
        "accounts/",
        include("accounts.urls"),
    ),

    # ---------------------------------------------------------
    # Operator Panel
    # ---------------------------------------------------------

    path(
        "operator/",
        include("operator_panel.urls"),
    ),
]