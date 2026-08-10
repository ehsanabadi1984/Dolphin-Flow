from django.urls import path

from .views import (
    dashboard,
    execute_transition,
    start_workflow,
    workflow_instance,
)


app_name = "operator_panel"


urlpatterns = [
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
]
