#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_SOURCE="$REPO_ROOT/deploy/systemd/dolphinplus-restore-worker.service"
SUDOERS_SOURCE="$REPO_ROOT/deploy/sudoers/dolphinplus-restore"

if [[ "$EUID" -ne 0 ]]; then
    echo "این نصب یک‌باره باید با دسترسی مدیر سیستم اجرا شود." >&2
    exit 1
fi

if [[ ! -x /opt/dolphinplus/backend/.venv/bin/celery ]]; then
    echo "محیط مجازی Dolphin-Flow در مسیر مورد انتظار پیدا نشد." >&2
    exit 1
fi

install -o root -g root -m 0644 "$SERVICE_SOURCE" /etc/systemd/system/dolphinplus-restore-worker.service
install -o root -g root -m 0440 "$SUDOERS_SOURCE" /etc/sudoers.d/dolphinplus-restore
visudo -cf /etc/sudoers.d/dolphinplus-restore
systemctl daemon-reload
systemctl enable --now dolphinplus-restore-worker.service
systemctl is-active --quiet dolphinplus-restore-worker.service

echo "Dolphin-Flow dedicated restore worker is installed and active."
