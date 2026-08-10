from django.urls import path

from .views import (
    dashboard,
    execute_transition,
    save_form_data,
    start_workflow,
    workflow_instance,
)


app_name = "operator_panel"


urlpatterns = [
    
    path(
    "workflow-instance/<int:instance_id>/save/",
    save_form_data,
    name="save_form_data",
    
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
]
