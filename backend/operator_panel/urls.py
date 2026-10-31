from django.urls import path
from . import views
from .dashboard_views import dashboard, dashboard_realtime
from .process_views import (
    assigned_tasks,
    hide_dashboard_process,
    my_processes,
    restore_dashboard_process,
    unfinished_processes,
    waiting_for_others,
    pending_acceptance_detail,
    pending_acceptances,
    accept_pending_acceptance,
    reject_pending_acceptance,
)
from .formula_views import formula_definitions, formula_field_options
from .views import (
    execute_transition,
    start_workflow,
    workflow_instance,
    notifications,
    mark_notification_as_read,
)
from .history_views import device_history, workflow_history
from .history_list_views import history_list
from workflow.form_print_views import form_print_preview
from workflow.file_share_views import (
    file_share_inbox, file_share_draft_delete, file_share_draft_update, file_share_message_detail,
    file_share_message_download, file_share_message_recall,
    file_share_message_respond, file_share_message_complete,
)
from workflow.form_file_services import (
    file_field_definitions,
    open_form_file,
    open_pending_acceptance_file,
    workflow_instance_with_files,
    delete_form_file,
)


app_name = "operator_panel"


urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("dashboard/realtime/", dashboard_realtime, name="dashboard_realtime"),
    path("history/", history_list, name="history_list"),
    path("my-processes/", my_processes, name="my_processes"),
    path("assigned-tasks/", assigned_tasks, name="assigned_tasks"),
    path("unfinished-processes/", unfinished_processes, name="unfinished_processes"),
    path("unfinished-processes/<int:instance_id>/hide/", hide_dashboard_process, name="hide_dashboard_process"),
    path("unfinished-processes/<int:instance_id>/restore/", restore_dashboard_process, name="restore_dashboard_process"),
    path("waiting-for-others/", waiting_for_others, name="waiting_for_others"),
    path("pending-acceptances/", pending_acceptances, name="pending_acceptances"),
    path("pending-acceptances/<int:transition_execution_id>/", pending_acceptance_detail, name="pending_acceptance_detail"),
    path("pending-acceptances/<int:transition_execution_id>/accept/", accept_pending_acceptance, name="accept_pending_acceptance"),
    path("pending-acceptances/<int:transition_execution_id>/reject/", reject_pending_acceptance, name="reject_pending_acceptance"),
    path("workflow/<int:workflow_id>/start/", start_workflow, name="start_workflow"),
    path("workflow-instance/<int:instance_id>/", workflow_instance_with_files, name="workflow_instance"),
    path("workflow-instance/<int:instance_id>/print-preview/", form_print_preview, name="form_print_preview"),
    path("workflow-instance/<int:instance_id>/history/", workflow_history, name="workflow_history"),
    path("workflow-instance/<int:instance_id>/device-group/<str:group_code>/device/<int:row_id>/delete/", views.delete_device, name="delete_device"),
    path("workflow-instance/<int:instance_id>/device/<int:device_id>/history/", device_history, name="device_history"),
    path("workflow-instance/<int:instance_id>/transition/<int:transition_id>/execute/", execute_transition, name="execute_transition"),
    path("device/lookup-by-imei/", views.lookup_device_by_imei, name="lookup_device_by_imei"),
    path("device-models-by-type/", views.device_models_by_type, name="device_models_by_type"),
    path("dependent-field-options/", views.dependent_field_options, name="dependent_field_options"),
    path("workflow-instance/<int:instance_id>/formula-definitions/", formula_definitions, name="formula_definitions"),
    path("formula-field-options/", formula_field_options, name="formula_field_options"),
    path("workflow-instance/<int:instance_id>/file-field-definitions/", file_field_definitions, name="file_field_definitions"),
    path("workflow-file/<int:file_id>/download/", open_form_file, name="download_form_file"),
    path("pending-acceptances/<int:transition_execution_id>/files/<int:file_id>/download/", open_pending_acceptance_file, name="download_pending_acceptance_file"),
    path("workflow-file/<int:file_id>/delete/", delete_form_file, name="delete_form_file"),
    path("file-shares/", file_share_inbox, name="file_share_inbox"),
    path("file-shares/drafts/<int:draft_id>/update/", file_share_draft_update, name="file_share_draft_update"),
    path("file-shares/drafts/<int:draft_id>/delete/", file_share_draft_delete, name="file_share_draft_delete"),
    path("file-shares/messages/<int:message_id>/", file_share_message_detail, name="file_share_message_detail"),
    path("file-shares/messages/<int:message_id>/download/", file_share_message_download, name="file_share_message_download"),
    path("file-shares/messages/<int:message_id>/respond/", file_share_message_respond, name="file_share_message_respond"),
    path("file-shares/messages/<int:message_id>/complete/", file_share_message_complete, name="file_share_message_complete"),
    path("file-shares/messages/<int:message_id>/recall/", file_share_message_recall, name="file_share_message_recall"),
    path("notifications/", notifications, name="notifications"),
    path("notifications/<int:notification_id>/read/", mark_notification_as_read, name="mark_notification_as_read"),
]
