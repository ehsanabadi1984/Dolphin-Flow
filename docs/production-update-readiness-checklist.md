# Production Update Readiness Checklist

> **Purpose:** A repeatable, evidence-based checklist for assessing data compatibility and operational readiness before updating the Production deployment.
>
> **Safety rule:** This checklist is initially read-only. Do not modify Production data, run repair commands, apply migrations manually, or stop/restart Product services as part of a check unless the change has been explicitly reviewed and approved.

## Status legend

- [ ] Not checked
- [x] Checked and passed
- [!] Issue found / action required
- [-] Not applicable

Record the date, application commit, database backup identifier, operator, and evidence for each Production run. Do not mark an item as passed based only on development-database observations.

## 1. Pre-update safeguards

- [ ] Confirm the target Git branch, commit, and release scope.
- [ ] Confirm a recent, restorable PostgreSQL backup is available.
- [ ] Confirm the corresponding media backup is available.
- [ ] Verify backup integrity and compatibility with the PostgreSQL client/server versions used by the restore procedure.
- [ ] Confirm the restore/recovery procedure and responsible operator are available.
- [ ] Review pending migrations and their expected effects; do not run them outside the approved deployment procedure.
- [ ] Capture the current state of Product services and the application health checks.
- [ ] Generate and retain the read-only data compatibility report described below.

## 2. Legacy workflow data compatibility

### 2.1 Missing `WorkflowStepExecution.assigned_to`

**Why this matters:** Older workflow executions may have no execution-level assignee even when their related `WorkflowStep.assigned_to` is populated. This can affect authorization to save or submit a form and continue an active workflow.

- [ ] Identify active executions where `assigned_to_id IS NULL`.
- [ ] For each affected row, inspect the related instance's current step and the step's configured assignee/policy.
- [ ] Distinguish the current active execution from completed, superseded, or historical executions.
- [ ] Check whether the workflow has moved since the execution was created; do not infer current responsibility from a stale step configuration.
- [ ] Produce a report with counts and affected execution/instance identifiers, without changing data.
- [ ] Define and review an explicit repair plan, including eligibility rules and stale-plan protection.
- [ ] Obtain approval before applying any repair.
- [ ] After an approved repair, verify that only intended active executions were changed and that the responsible user has the required effective `EXECUTE` permission.

**Current policy:** Do not bulk-copy `WorkflowStep.assigned_to` into every historical execution. A repair must be limited to explicitly validated active executions and must not rewrite completed history.

### 2.2 Missing `WorkflowStepExecution.completed_by`

**Why this matters:** Historical completion summaries must not attribute a completion to a user without reliable evidence.

Expected interpretation:

| Execution state | Interpretation |
|---|---|
| `is_submitted = false` | Not a completed execution; exclude it from completed-history attribution. |
| `is_submitted = true` and `completed_by_id` is populated | Attribute completion to `completed_by`. |
| `is_submitted = true` and `completed_by_id IS NULL` | Preserve as a legacy completion with unknown completer. Do not infer the completer from `performed_by`. |

- [ ] Review all current code paths that submit/complete a `WorkflowStepExecution`.
- [ ] Confirm new completion paths populate `completed_by` consistently.
- [ ] Review the model and migrations that introduced `completed_by`; determine whether any historical backfill was implemented and what evidence it used.
- [ ] Confirm summary/history queries consider submitted executions only and use `completed_by` for user attribution.
- [ ] Confirm NULL `completed_by` records remain preserved as unknown legacy history.
- [ ] Check query shape and indexes for the batch summary path; avoid per-instance/N+1 queries.
- [ ] Record any required code or data remediation separately; do not backfill from `performed_by` merely because `completed_by` is NULL.

**Current policy:** Preserve legacy history, but do not guess the identity of its completer. A NULL `completed_by` is an unknown identity, not permission to use `performed_by` as a fallback.

### 2.3 Other workflow lifecycle compatibility checks

- [ ] Verify active executions match the instance's current step.
- [ ] Review legacy executions affected by step reassignment or workflow override.
- [ ] Confirm superseded/removed executions are not treated as current actionable work.
- [ ] Confirm returning to a previously visited step creates/uses the intended new execution lifecycle.
- [ ] Verify assignment policies and effective `EXECUTE` permissions for active steps.
- [ ] Verify timeline and assignment-history records remain readable and correctly ordered.
- [ ] Verify historical summary behavior matches the documented product behavior.

## 3. Application and authorization checks

- [ ] Verify only the assignee of the active execution can save a draft.
- [ ] Verify an unassigned active execution cannot be used to bypass execution authorization.
- [ ] Verify a previous execution's assignee cannot act after reassignment or step re-entry.
- [ ] Verify `EXECUTE` permission is checked independently from transition permission.
- [ ] Verify workflow start and transition destination assignment/permission behavior.
- [ ] Run the focused automated test suites for every changed workflow area.
- [ ] Record known unrelated/legacy test failures separately; do not silently classify them as regressions or ignore them without review.

## 4. Deployment and post-update verification

- [ ] Follow the approved deployment runbook and maintenance/quiescence sequence.
- [ ] Apply migrations only through the approved deployment procedure.
- [ ] Verify application startup and health checks.
- [ ] Verify database connectivity and media availability.
- [ ] Verify Celery and other required background services are healthy.
- [ ] Open representative active workflows and confirm the correct current assignee is shown.
- [ ] Verify authorized users can continue active workflows and unauthorized users cannot.
- [ ] Verify historical workflow summaries and timelines remain accessible.
- [ ] Review application, worker, and database logs for errors.
- [ ] Record the final release commit, migration state, verification results, and any follow-up actions.

## 5. Compatibility report template

Create a report for each Production update. At minimum include:

| Field | Value |
|---|---|
| Date/time | |
| Product release commit | |
| Database backup reference | |
| PostgreSQL server/client versions | |
| Active executions missing `assigned_to` | |
| Submitted executions missing `completed_by` | |
| Other compatibility findings | |
| Approved repairs (if any) | |
| Focused test results | |
| Post-update verification | |
| Operator / reviewer | |

Do not include secrets, credentials, or unnecessary personal data in the report.

## 6. Change control

1. Read-only checks and reporting may be performed as part of preflight.
2. Any data repair must have documented eligibility rules, a reviewable plan, a backup, and explicit approval.
3. Never use `performed_by` as an automatic substitute for `completed_by`.
4. Never assign historical executions in bulk solely from the current step configuration.
5. Keep findings, approved repairs, and deployment verification evidence with the release record.
6. Update this checklist when a new legacy-data or deployment risk is discovered.

---

**Document status:** Initial checklist. The two legacy-field checks (`assigned_to` and `completed_by`) are identified, but their full code/migration review and Production data assessment must be completed before they can be marked as resolved.
