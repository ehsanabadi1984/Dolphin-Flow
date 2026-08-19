from django.urls import path
from . import views
from .views import (
    dashboard,
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
        "workflow/<int:instance_id>/submit-form/",
        views.submit_form,
        name="submit_form",
    ),
    
    path(
        "",
        dashboard,
        name="dashboard",
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
        "workflow-instance/<int:instance_id>/transition/<int:transition_id>/execute/",
        execute_transition,
        name="execute_transition",
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
