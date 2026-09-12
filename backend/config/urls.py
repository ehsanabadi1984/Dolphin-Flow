"""
URL configuration for config project.
"""

from django.urls import include, path
from django.views.generic import RedirectView

from workflow.admin import (
    workflow_dynamic_steps,
    workflow_dynamic_transitions,
    formfield_model_fields,
    dolphin_admin_site,
)
from workflow.process_workspace import (
    process_workspace_list,
    process_workspace,
)
from workflow.form_workspace import form_workspace
from workflow.form_workspace_api import workspace_model_fields
from workflow.access_workspace import (
    access_security_workspace_list,
    access_security_workspace,
)
from workflow.data_sources_workspace import data_sources_workspace
from workflow.device_catalog_workspace import device_catalog_workspace
from workflow.sla_calendar_workspace import sla_calendar_workspace


urlpatterns = [
    path("", RedirectView.as_view(pattern_name="accounts:login", permanent=False), name="root"),

    path("admin/workflow/process-workspace/", dolphin_admin_site.admin_view(process_workspace_list), name="process_workspace_list"),
    path("admin/workflow/process-workspace/<int:workflow_id>/", dolphin_admin_site.admin_view(process_workspace), name="process_workspace"),

    path("admin/workflow/form-workspace/<int:workflow_id>/", dolphin_admin_site.admin_view(form_workspace), name="form_workspace"),
    path("admin/workflow/form-workspace/model-fields/", dolphin_admin_site.admin_view(workspace_model_fields), name="workspace_model_fields"),

    path("admin/workflow/access-security/", dolphin_admin_site.admin_view(access_security_workspace_list), name="access_security_workspace_list"),
    path("admin/workflow/access-security/<int:workflow_id>/", dolphin_admin_site.admin_view(access_security_workspace), name="access_security_workspace"),

    path("admin/workflow/data-sources/", dolphin_admin_site.admin_view(data_sources_workspace), name="data_sources_workspace"),
    path("admin/workflow/device-catalog/", dolphin_admin_site.admin_view(device_catalog_workspace), name="device_catalog_workspace"),
    path("admin/workflow/sla-calendar/", dolphin_admin_site.admin_view(sla_calendar_workspace), name="sla_calendar_workspace"),

    path("admin/workflow/dynamic/steps/", dolphin_admin_site.admin_view(workflow_dynamic_steps), name="workflow_dynamic_steps"),
    path("admin/workflow/dynamic/transitions/", dolphin_admin_site.admin_view(workflow_dynamic_transitions), name="workflow_dynamic_transitions"),
    path("admin/workflow/dynamic/formfield-model-fields/", dolphin_admin_site.admin_view(formfield_model_fields), name="formfield_model_fields"),

    path("admin/", dolphin_admin_site.urls),
    path("accounts/", include("accounts.urls")),
    path("operator/", include("operator_panel.urls")),
]
