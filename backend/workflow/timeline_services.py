"""Read-only event aggregation for a single workflow instance timeline."""

from workflow.models import (
    FileShareMessageEvent,
    WorkflowInstance,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
    WorkflowTransitionExecution,
)


def _user_label(user):
    if not user:
        return "—"
    full_name = " ".join(
        part for part in (user.first_name, user.last_name) if part
    ).strip()
    return full_name or user.get_username()


def _event(event_type, event_id, timestamp, title, user=None, description="",
           **extra):
    return {
        "type": event_type,
        "id": str(event_id),
        "performed_at": timestamp,
        "title": title,
        "user": _user_label(user),
        "description": description or "",
        "is_submitted": False,
        "sla_completed": False,
        "sla_breached": False,
        **extra,
    }


def build_instance_timeline_events(instance):
    """Return a deterministic, chronological list of persisted instance events.

    This function only reads existing workflow records. It does not create
    events, change workflow state, or infer timestamps that were not recorded.
    """
    if not isinstance(instance, WorkflowInstance):
        raise TypeError("instance must be a WorkflowInstance")

    events = [
        _event(
            "start",
            f"instance-{instance.pk}",
            instance.started_at,
            "شروع فرآیند",
            instance.started_by,
            f"فرآیند «{instance.workflow.name}» شروع شد.",
        )
    ]

    executions = (
        WorkflowStepExecution.objects.filter(instance=instance)
        .select_related(
            "workflow_step", "performed_by", "entered_by",
            "assigned_to", "completed_by",
        )
        .prefetch_related("assignment_history")
    )
    for execution in executions:
        events.append(
            _event(
                "step",
                f"step-{execution.pk}",
                execution.performed_at,
                f"ورود به مرحله «{execution.workflow_step.name}»",
                execution.entered_by or execution.performed_by,
                execution.notes,
                execution_id=execution.pk,
                entered_by=_user_label(execution.entered_by),
                assigned_to=_user_label(execution.assigned_to),
                assigned_at=execution.assigned_at,
                completed_by=_user_label(execution.completed_by),
                submitted_at=execution.submitted_at,
                is_submitted=execution.is_submitted,
                history=(execution.data or {}).get("history"),
                sla_started_at=execution.sla_started_at,
                sla_due_at=execution.sla_due_at,
                sla_warning_at=execution.sla_warning_at,
                sla_warning_sent_at=execution.sla_warning_sent_at,
                sla_completed_at=execution.sla_completed_at,
                sla_breached_at=execution.sla_breached_at,
                sla_completed=bool(execution.sla_completed_at),
                sla_breached=bool(execution.sla_breached_at),
            )
        )

    assignments = (
        WorkflowStepAssignmentHistory.objects.filter(
            step_execution__instance=instance
        )
        .select_related(
            "step_execution__workflow_step",
            "previous_assignee", "new_assignee", "changed_by",
        )
    )
    for assignment in assignments:
        step_name = assignment.step_execution.workflow_step.name
        events.append(
            _event(
                "assignment",
                f"assignment-{assignment.pk}",
                assignment.created_at,
                f"تغییر مسئول مرحله «{step_name}»",
                assignment.changed_by,
                assignment.reason,
                previous_assignee=_user_label(assignment.previous_assignee),
                new_assignee=_user_label(assignment.new_assignee),
                assignment_source=assignment.get_source_display(),
                assignment_source_code=assignment.source,
                step_execution_id=assignment.step_execution_id,
            )
        )

    transitions = (
        WorkflowTransitionExecution.objects.filter(instance=instance)
        .select_related(
            "transition__from_step", "transition__to_step",
            "performed_by", "accepted_by", "rejected_by",
        )
    )
    for transition_execution in transitions:
        transition = transition_execution.transition
        destination = (
            transition.to_step.name if transition.to_step_id
            else "تکمیل فرآیند"
        )
        route = f"{transition.from_step.name} → {destination}"
        events.append(
            _event(
                "transition",
                f"transition-{transition_execution.pk}",
                transition_execution.performed_at,
                transition.name,
                transition_execution.performed_by,
                route,
                transition_execution_id=transition_execution.pk,
                transition_status=transition_execution.get_status_display(),
                transition_status_code=transition_execution.status,
                from_step=transition.from_step.name,
                to_step=destination,
                resolved_at=transition_execution.resolved_at,
                decision_user=_user_label(
                    transition_execution.accepted_by
                    or transition_execution.rejected_by
                ),
                notes=transition_execution.notes,
            )
        )
        if transition_execution.status in {
            WorkflowTransitionExecution.Status.ACCEPTED,
            WorkflowTransitionExecution.Status.REJECTED,
        }:
            decision_user = (
                transition_execution.accepted_by
                if transition_execution.status
                == WorkflowTransitionExecution.Status.ACCEPTED
                else transition_execution.rejected_by
            )
            outcome = transition_execution.get_status_display()
            events.append(
                _event(
                    "transition_resolution",
                    f"transition-resolution-{transition_execution.pk}",
                    transition_execution.resolved_at,
                    f"تعیین تکلیف انتقال: {outcome}",
                    decision_user,
                    (
                        "زمان دقیق ثبت نشده است."
                        if transition_execution.resolved_at is None
                        else ""
                    ),
                    transition_execution_id=transition_execution.pk,
                    transition_status=transition_execution.status,
                    resolved_at=transition_execution.resolved_at,
                    from_step=transition.from_step.name,
                    to_step=destination,
                )
            )

    file_share_events = (
        FileShareMessageEvent.objects.filter(
            message__workflow_instance=instance
        )
        .select_related(
            "actor", "message__sender", "message__recipient",
            "message__workflow_step",
        )
    )
    for share_event in file_share_events:
        message = share_event.message
        actor = share_event.actor or (
            message.sender
            if share_event.event_type in {
                FileShareMessageEvent.EventType.CREATED,
                FileShareMessageEvent.EventType.SENT,
            }
            else None
        )
        title = f"اشتراک فایل: {share_event.get_event_type_display()}"
        description = (
            f"فرستنده: {_user_label(message.sender)}؛ "
            f"گیرنده: {_user_label(message.recipient)}"
        )
        if message.subject:
            description += f"؛ موضوع: {message.subject}"
        events.append(
            _event(
                "file_share",
                f"file-share-{share_event.pk}",
                share_event.created_at,
                title,
                actor,
                description,
                file_share_event_id=share_event.pk,
                file_share_event_type=share_event.event_type,
                sender=_user_label(message.sender),
                recipient=_user_label(message.recipient),
                interaction_type=message.get_interaction_type_display(),
                message_status=message.get_status_display(),
                workflow_step=(
                    message.workflow_step.name
                    if message.workflow_step_id else None
                ),
                details=share_event.details or {},
            )
        )

    # A finish transition is the durable record of each completion cycle.
    # Keep these events even if an Override later reopens the instance and
    # clears WorkflowInstance.completed_at.
    finish_executions = [
        item for item in transitions
        if item.transition.to_step_id is None
        and item.status == WorkflowTransitionExecution.Status.ACCEPTED
    ]
    for finish_execution in finish_executions:
        events.append(
            _event(
                "instance_completed",
                f"instance-completed-transition-{finish_execution.pk}",
                finish_execution.performed_at,
                "تکمیل فرآیند",
                finish_execution.performed_by,
                f"فرآیند «{instance.workflow.name}» تکمیل شد.",
                transition_execution_id=finish_execution.pk,
            )
        )

    # Compatibility for older completed instances that predate persisted
    # finish-transition records. Do not duplicate a recorded completion.
    if instance.completed_at and not finish_executions:
        events.append(
            _event(
                "instance_completed",
                f"instance-completed-{instance.pk}",
                instance.completed_at,
                "تکمیل فرآیند",
                None,
                f"فرآیند «{instance.workflow.name}» تکمیل شد.",
            )
        )

    # Stable tie-breakers prevent events with identical timestamps from
    # changing order between requests.
    events.sort(
        key=lambda item: (
            item["performed_at"] is None,
            item["performed_at"],
            item["type"],
            item["id"],
        )
    )
    return events
