# Automated restore worker

The admin "Restore" action now follows this server-side flow:

1. The normal Celery worker validates the archive and prepares isolated database/media staging resources.
2. It publishes a cutover task to the dedicated `restore_cutover` queue.
3. `dolphinplus-restore-worker.service` owns that queue and remains running while the orchestrator stops Daphne, the ordinary Celery worker, and Celery Beat.
4. The orchestrator performs the database/media swap, migrations, health checks, service restart, audit finalization, and maintenance release.
5. If the dedicated worker is interrupted while the maintenance marker is active, the task is retried and the journal-driven recovery command runs before any new cutover attempt.

## One-time server provisioning

This is deployment setup, not an action for Dolphin-Flow administrators using the panel.

On the product server, from the checked-out repository, run the installer once as root:

```bash
sudo bash deploy/scripts/install-restore-worker.sh
```

The installer installs the dedicated systemd worker and a narrowly scoped sudoers policy. The policy allows the worker account `ehsan` to start/stop only these application units:

- `dolphinplus-daphne`
- `dolphinplus-celery`
- `dolphinplus-celery-beat`

The restore worker itself is deliberately excluded from the stop list and privilege policy.

The application setting `RESTORE_SERVICE_UNITS` defaults to those three units. If deployment overrides that setting, the sudoers policy must be reviewed and updated with the same exact unit names; do not grant wildcard systemctl access.

## Administrator experience

After provisioning, an authorized administrator only selects a successful backup and confirms Restore in the admin panel. No shell, SSH, service names, or command-line steps are exposed to the administrator. The restore history page refreshes while the operation is active and shows the terminal success/failure result when the application is available again.

## Safety behavior

- The dedicated worker consumes only `restore_cutover`; it is not stopped during cutover.
- Cutover tasks use late acknowledgement and reject-on-worker-loss.
- The worker service is configured to restart automatically.
- The durable restore journal and maintenance marker are used to distinguish safe retry from rollback/recovery.
- If recovery cannot prove the previous system is healthy, maintenance remains active rather than exposing a partially restored application.
