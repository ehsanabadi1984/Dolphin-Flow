from workflow.models import WorkflowInstanceEvent


def _user_label(user):
    if user is None:
        return ""
    full_name = " ".join(
        part for part in (user.first_name, user.last_name) if part
    ).strip()
    return full_name or user.get_username()


class WorkflowInstanceEventService:
    """Persist an execution's entry/override event independently of its row."""

    @staticmethod
    def record_step_entry(
        *,
        execution,
        actor=None,
        event_type=None,
        sla_stopped_at=None,
        sla_stop_reason="",
    ):
        data = execution.data if isinstance(execution.data, dict) else {}
        override = data.get("override")
        if event_type is None:
            event_type = (
                WorkflowInstanceEvent.EventType.OVERRIDE
                if isinstance(override, dict)
                else WorkflowInstanceEvent.EventType.STEP_ENTERED
            )

        actor = actor or execution.entered_by or execution.performed_by
        actor_source = (
            "entered_by" if execution.entered_by_id
            else "performed_by_legacy" if execution.performed_by_id
            else "unknown"
        )
        details = {
            "execution_id": execution.pk,
            "actor_source": actor_source,
            "notes": execution.notes or "",
            "is_submitted": execution.is_submitted,
            "submitted_at": (
                execution.submitted_at.isoformat()
                if execution.submitted_at else None
            ),
            "assigned_at": (
                execution.assigned_at.isoformat()
                if execution.assigned_at else None
            ),
            "completed_by_id": execution.completed_by_id,
            "completed_by_label": _user_label(execution.completed_by),
            "sla_started_at": (
                execution.sla_started_at.isoformat()
                if execution.sla_started_at else None
            ),
            "sla_due_at": (
                execution.sla_due_at.isoformat()
                if execution.sla_due_at else None
            ),
            "sla_warning_at": (
                execution.sla_warning_at.isoformat()
                if execution.sla_warning_at else None
            ),
            "sla_warning_sent_at": (
                execution.sla_warning_sent_at.isoformat()
                if execution.sla_warning_sent_at else None
            ),
            "sla_completed_at": (
                execution.sla_completed_at.isoformat()
                if execution.sla_completed_at else None
            ),
            "sla_breached_at": (
                execution.sla_breached_at.isoformat()
                if execution.sla_breached_at else None
            ),
            "history": data.get("history"),
            "override": override if isinstance(override, dict) else {},
        }
        if sla_stopped_at is not None:
            details["sla_stopped_at"] = sla_stopped_at.isoformat()
            details["sla_stop_reason"] = sla_stop_reason or ""

        event, created = WorkflowInstanceEvent.objects.get_or_create(
            instance_id=execution.instance_id,
            execution_id=execution.pk,
            defaults={
                "workflow_step_id": execution.workflow_step_id,
                "event_type": event_type,
                "actor": actor,
                "actor_label": _user_label(actor),
                "assigned_to": execution.assigned_to,
                "assigned_to_label": _user_label(execution.assigned_to),
                "occurred_at": execution.performed_at,
                "details": details,
            },
        )
        if not created and sla_stopped_at is not None:
            existing_details = dict(event.details or {})
            existing_details["sla_stopped_at"] = sla_stopped_at.isoformat()
            existing_details["sla_stop_reason"] = sla_stop_reason or ""
            event.details = existing_details
            event.save(update_fields=["details"])
        return event
