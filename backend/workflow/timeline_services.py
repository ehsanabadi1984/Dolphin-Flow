"""Read-only event aggregation for a single workflow instance timeline."""

from workflow.models import (
    FileShareMessageEvent,
    WorkflowInstance,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
    WorkflowInstanceEvent,
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
        "sla_stopped": False,
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

    audit_events = list(
        WorkflowInstanceEvent.objects.filter(instance=instance)
        .select_related("workflow_step", "actor", "assigned_to")
    )
    event_execution_ids = {
        item.execution_id for item in audit_events
        if item.execution_id is not None
    }
    live_executions = {
        execution.pk: execution
        for execution in WorkflowStepExecution.objects.filter(
            instance=instance,
            pk__in=event_execution_ids,
        ).select_related("entered_by", "performed_by", "assigned_to", "completed_by")
    }
    for audit_event in audit_events:
        details = dict(audit_event.details or {})
        live_execution = live_executions.get(audit_event.execution_id)
        if live_execution is not None:
            live_data = (
                live_execution.data
                if isinstance(live_execution.data, dict) else {}
            )
            details.update({
                "notes": live_execution.notes or "",
                "is_submitted": live_execution.is_submitted,
                "submitted_at": live_execution.submitted_at,
                "assigned_at": live_execution.assigned_at,
                "completed_by_label": _user_label(live_execution.completed_by),
                "sla_started_at": live_execution.sla_started_at,
                "sla_due_at": live_execution.sla_due_at,
                "sla_warning_at": live_execution.sla_warning_at,
                "sla_warning_sent_at": live_execution.sla_warning_sent_at,
                "sla_completed_at": live_execution.sla_completed_at,
                "sla_breached_at": live_execution.sla_breached_at,
                "history": live_data.get("history"),
                "override": live_data.get("override", details.get("override")),
            })
        override_metadata = details.get("override")
        override_metadata = (
            override_metadata if isinstance(override_metadata, dict) else {}
        )
        is_override = (
            audit_event.event_type == WorkflowInstanceEvent.EventType.OVERRIDE
        )
        actor_label = (
            audit_event.actor_label
            or _user_label(audit_event.actor)
        )
        assigned_to_label = (
            audit_event.assigned_to_label
            or _user_label(audit_event.assigned_to)
        )
        event = _event(
            "override" if is_override else "step",
            f"step-{audit_event.execution_id or audit_event.pk}",
            audit_event.occurred_at,
            (
                "اصلاح مسیر فرآیند"
                if is_override
                else f"ورود به مرحله «{audit_event.workflow_step.name}»"
            ),
            audit_event.actor,
            "" if is_override else details.get("notes", ""),
            user_role_label=(
                "ثبت‌کننده ورود به مرحله"
                if details.get("actor_source") == "entered_by"
                else "عامل ثبت‌شده در داده Legacy (performed_by؛ نه لزوماً تکمیل‌کننده)"
                if details.get("actor_source") == "performed_by_legacy"
                else "عامل ثبت نشده"
            ),
            user_source=details.get("actor_source", "unknown"),
            execution_id=audit_event.execution_id,
            override_from_step=(
                override_metadata.get("from_step_name") or "—"
            ),
            override_to_step=(
                override_metadata.get("to_step_name")
                or audit_event.workflow_step.name
            ),
            override_reason=override_metadata.get("reason") or "—",
            entered_by=actor_label or "—",
            assigned_to=assigned_to_label or "—",
            assigned_at=details.get("assigned_at"),
            completed_by=details.get("completed_by_label") or "—",
            submitted_at=details.get("submitted_at"),
            is_submitted=bool(details.get("is_submitted")),
            history=details.get("history"),
            sla_started_at=details.get("sla_started_at"),
            sla_due_at=details.get("sla_due_at"),
            sla_warning_at=details.get("sla_warning_at"),
            sla_warning_sent_at=details.get("sla_warning_sent_at"),
            sla_completed_at=details.get("sla_completed_at"),
            sla_breached_at=details.get("sla_breached_at"),
            sla_stopped_at=details.get("sla_stopped_at"),
            sla_stop_reason=details.get("sla_stop_reason", ""),
            sla_completed=bool(details.get("sla_completed_at")),
            sla_breached=bool(details.get("sla_breached_at")),
            sla_stopped=bool(details.get("sla_stopped_at")),
        )
        event["user"] = actor_label or "—"
        events.append(event)

    executions = (
        WorkflowStepExecution.objects.filter(instance=instance)
        .exclude(pk__in=event_execution_ids)
        .select_related(
            "workflow_step", "performed_by", "entered_by",
            "assigned_to", "completed_by",
        )
        .prefetch_related("assignment_history")
    )
    for execution in executions:
        assignment_history = list(execution.assignment_history.all())
        override_assignment = next(
            (
                item for item in assignment_history
                if item.source == WorkflowStepAssignmentHistory.Source.OVERRIDE
            ),
            None,
        )
        execution_data = execution.data or {}
        override_metadata = execution_data.get("override")
        is_override = (
            override_assignment is not None
            or isinstance(override_metadata, dict)
        )
        override_metadata = (
            override_metadata if isinstance(override_metadata, dict) else {}
        )
        override_from_step = (
            override_metadata.get("from_step_name")
            or "—"
        )
        override_to_step = (
            override_metadata.get("to_step_name")
            or execution.workflow_step.name
        )
        override_reason = (
            override_metadata.get("reason")
            or (override_assignment.reason if override_assignment else "")
            or "—"
        )
        event_actor = execution.entered_by or execution.performed_by
        event_actor_source = (
            "entered_by" if execution.entered_by_id
            else "performed_by_legacy" if execution.performed_by_id
            else "unknown"
        )
        event = _event(
            "override" if is_override else "step",
            f"step-{execution.pk}",
            execution.performed_at,
            (
                "اصلاح مسیر فرآیند"
                if is_override
                else f"ورود به مرحله «{execution.workflow_step.name}»"
            ),
            event_actor,
            "" if is_override else execution.notes,
            user_role_label=(
                "ثبت‌کننده ورود به مرحله"
                if event_actor_source == "entered_by"
                else "عامل ثبت‌شده در داده Legacy (performed_by؛ نه لزوماً تکمیل‌کننده)"
                if event_actor_source == "performed_by_legacy"
                else "عامل ثبت نشده"
            ),
            user_source=event_actor_source,
            execution_id=execution.pk,
            override_from_step=override_from_step,
            override_to_step=override_to_step,
            override_reason=override_reason,
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
        events.append(event)

    assignments = (
        WorkflowStepAssignmentHistory.objects.filter(instance=instance)
        .select_related(
            "workflow_step", "previous_assignee", "new_assignee", "changed_by",
        )
    )
    for assignment in assignments:
        step_name = assignment.workflow_step.name
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
            "transition__reject_to_step",
            "performed_by", "accepted_by", "rejected_by",
            "proposed_assignee",
        )
    )
    for transition_execution in transitions:
        transition = transition_execution.transition
        is_rejected = (
            transition_execution.status
            == WorkflowTransitionExecution.Status.REJECTED
        )
        if is_rejected:
            destination = (
                transition.reject_to_step.name
                if transition.reject_to_step_id
                else "مقصد بازگشت ثبت نشده"
            )
        else:
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
                proposed_assignee=_user_label(
                    transition_execution.proposed_assignee
                ),
                proposed_assignee_id=transition_execution.proposed_assignee_id,
                requires_acceptance=transition.requires_acceptance,
                notes=transition_execution.notes,
            )
        )
        if (
            transition.requires_acceptance
            and transition_execution.status in {
                WorkflowTransitionExecution.Status.ACCEPTED,
                WorkflowTransitionExecution.Status.REJECTED,
                WorkflowTransitionExecution.Status.SUPERSEDED,
            }
        ):
            is_superseded = (
                transition_execution.status
                == WorkflowTransitionExecution.Status.SUPERSEDED
            )
            if is_superseded:
                decision_user = None
                resolution_description = (
                    "این درخواست در پی اصلاح مدیریتی مسیر منسوخ شد؛ "
                    "این رویداد به معنی پذیرش یا رد درخواست نیست."
                )
                resolution_actor_label = "اصلاح مدیریتی مسیر"
            else:
                decision_user = (
                    transition_execution.accepted_by
                    if transition_execution.status
                    == WorkflowTransitionExecution.Status.ACCEPTED
                    else transition_execution.rejected_by
                )
                resolution_description = (
                    "زمان دقیق ثبت نشده است."
                    if transition_execution.resolved_at is None
                    else ""
                )
                resolution_actor_label = "تصمیم‌گیرنده"
            outcome = transition_execution.get_status_display()
            events.append(
                _event(
                    "transition_resolution",
                    f"transition-resolution-{transition_execution.pk}",
                    transition_execution.resolved_at,
                    f"تعیین تکلیف انتقال: {outcome}",
                    decision_user,
                    resolution_description,
                    transition_execution_id=transition_execution.pk,
                    transition_status=transition_execution.status,
                    resolved_at=transition_execution.resolved_at,
                    resolution_actor_label=resolution_actor_label,
                    from_step=transition.from_step.name,
                    to_step=destination,
                    proposed_assignee=_user_label(
                        transition_execution.proposed_assignee
                    ),
                    proposed_assignee_id=transition_execution.proposed_assignee_id,
                    timestamp_missing=transition_execution.resolved_at is None,
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

    # Keep equal-timestamp events in a stable, semantic order. The final
    # identifier component is numeric so step-10 follows step-9, not step-1.
    event_type_order = {
        "start": 0,
        "step": 10,
        "override": 11,
        "assignment": 20,
        "transition": 30,
        "transition_resolution": 40,
        "file_share": 50,
        "instance_completed": 60,
    }

    def numeric_event_id(event_id):
        suffix = str(event_id).rsplit("-", 1)[-1]
        try:
            return (0, int(suffix))
        except (TypeError, ValueError):
            return (1, str(event_id))

    events.sort(
        key=lambda item: (
            item["performed_at"] is None,
            item["performed_at"],
            event_type_order.get(item["type"], 99),
            numeric_event_id(item["id"]),
            item["id"],
        )
    )
    return events
