"""Read-only inventory of restore journals left by interrupted operations.

This module deliberately does not perform cleanup, rollback, or cutover. It
only classifies durable journal files so a later recovery command can make an
explicit, validated decision.
"""

import re
from pathlib import Path

from django.conf import settings

from .restore_journal import RestoreJournal
from .restore_services import RestoreError

_OPERATION_FILE_RE = re.compile(r"^[a-f0-9]{32}\.json$")

_TERMINAL_PHASES = {"COMPLETED", "ROLLED_BACK"}


def inspect_restore_journals(root=None):
    """Return a deterministic, read-only inventory of journal files."""
    configured_root = root or getattr(
        settings,
        "RESTORE_JOURNAL_ROOT",
        Path(settings.BACKUP_ROOT) / ".restore-journal",
    )
    journal_root = Path(configured_root).expanduser().resolve()

    if not journal_root.exists():
        return []
    if not journal_root.is_dir():
        raise RestoreError("مسیر Journal بازیابی یک پوشه معتبر نیست.")

    inventory = []
    for path in sorted(journal_root.iterdir(), key=lambda item: item.name):
        if path.name == ".restore-operation.lock" or path.name.startswith("."):
            continue
        if path.suffix != ".json":
            continue

        if not _OPERATION_FILE_RE.fullmatch(path.name):
            inventory.append({
                "operation_id": path.stem,
                "status": "INVALID",
                "recovery_required": True,
                "error": "نام فایل Journal معتبر نیست.",
            })
            continue

        operation_id = path.stem
        if path.is_symlink():
            inventory.append({
                "operation_id": operation_id,
                "status": "INVALID",
                "recovery_required": True,
                "error": "فایل Journal نمی‌تواند Symlink باشد.",
            })
            continue

        try:
            payload = RestoreJournal(operation_id, root=journal_root).read()
        except RestoreError as exc:
            inventory.append({
                "operation_id": operation_id,
                "status": "INVALID",
                "recovery_required": True,
                "error": str(exc),
            })
            continue

        phase = payload["phase"]
        inventory.append({
            "operation_id": operation_id,
            "restore_id": payload["restore_id"],
            "phase": phase,
            "updated_at": payload["updated_at"],
            "database": payload["database"],
            "media": payload["media"],
            "error": payload["error"],
            "status": "TERMINAL" if phase in _TERMINAL_PHASES else "INTERRUPTED",
            "recovery_required": phase not in _TERMINAL_PHASES,
        })

    return inventory
