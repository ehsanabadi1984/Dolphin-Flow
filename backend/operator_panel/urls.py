from django.urls import path
from . import views
from .dashboard_views import dashboard, dashboard_realtime
from .process_views import my_processes
from .formula_views import formula_definitions
from .views import (
    execute_transition,
    start_workflow,
    workflow_instance,
    clear_form_data,
    notifications,
    mark_notification_as_read,
)


app_name = "operator_panel"


urlpatterns = [

    path(
        "workflow-instance/<int:instance_id>/clear/",
        clear_form_data,
        name="clear_form_data",
    ),

    path(
        "",
        dashboard,
        name="dashboard",
    ),

    path(
        "dashboard/realtime/",
        dashboard_realtime,
        name="dashboard_realtime",
    ),

    path(
        "my-processes/",
        my_processes,
        name="my_processes",
    ),

    path(
        "workflow/<int:workflow_id>/start/",
        start_workflow,
        name="start_workflow",
    ),

    path(
        "workflow-instance/<int:instance_id>/",
        workflow_instance,
        name="workflow_instance",
    ),

    path(
        "workflow-instance/<int:instance_id>/device-group/<str:group_code>/device/<int:instance_device_id>/delete/",
        views.delete_device,
        name="delete_device",
    ),

    path(
        "workflow-instance/<int:instance_id>/device/<int:device_id>/history/",
        views.device_history,
        name="device_history",
    ),

    path(
        "workflow-instance/<int:instance_id>/transition/<int:transition_id>/execute/",
        execute_transition,
        name="execute_transition",
    ),

    path(
        "device/lookup-by-imei/",
        views.lookup_device_by_imei,
        name="lookup_device_by_imei",
    ),

    path(
        "dependent-field-options/",
        views.dependent_field_options,
        name="dependent_field_options",
    ),

    path(
        "workflow-instance/<int:instance_id>/formula-definitions/",
        formula_definitions,
        name="formula_definitions",
    ),

    path(
        "notifications/",
        notifications,
        name="notifications",
    ),

    path(
        "notifications/<int:notification_id>/read/",
        mark_notification_as_read,
        name="mark_notification_as_read",
    ),
]
