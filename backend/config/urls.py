"""
URL configuration for config project.
"""

from django.urls import include, path

from workflow.admin import (
    workflow_dynamic_steps,
    workflow_dynamic_transitions,
    formfield_model_fields,
    dolphin_admin_site,

)


urlpatterns = [
    # ---------------------------------------------------------
    # Workflow Dynamic Select Endpoints
    # ---------------------------------------------------------

    path(
        "admin/workflow/dynamic/steps/",
        dolphin_admin_site.admin_view(workflow_dynamic_steps),
        name="workflow_dynamic_steps",
    ),

    path(
        "admin/workflow/dynamic/transitions/",
        dolphin_admin_site.admin_view(workflow_dynamic_transitions),
        name="workflow_dynamic_transitions",
    ),

    path(
        "admin/workflow/dynamic/formfield-model-fields/",
        dolphin_admin_site.admin_view(formfield_model_fields),
        name="formfield_model_fields",
    ),

    # ---------------------------------------------------------
    # Django Admin
    # ---------------------------------------------------------

    path(
        "admin/",
        dolphin_admin_site.urls,
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