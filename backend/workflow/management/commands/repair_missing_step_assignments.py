import hashlib
import hmac
import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from workflow.assignment_services import WorkflowStepAssignmentService
from workflow.models import (
    WorkflowInstance,
    WorkflowStep,
    WorkflowStepAssignmentHistory,
    WorkflowStepExecution,
)


PLAN_VERSION = 1
REPAIR_REASON = (
    "بازیابی خودکار تخصیص ثابتِ ثبت‌نشده؛ "
    "فرمان repair_missing_step_assignments"
)


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _plan_digest(plan):
    payload = {key: value for key, value in plan.items() if key != "sha256"}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class Command(BaseCommand):
    help = (
        "گزارش‌گیری یا بازیابی کنترل‌شده مسئولِ خالی در اجراهای فعالِ "
        "مرحله فعلی با سیاست FIXED."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="اعمال اصلاح فقط روی نامزدهای واجد شرایط موجود در فایل طرح تأییدشده.",
        )
        parser.add_argument(
            "--plan-out",
            help="مسیر فایل JSON برای ذخیره گزارش/طرح dry-run؛ فایل موجود بازنویسی نمی‌شود.",
        )
        parser.add_argument(
            "--plan-file",
            help="فایل JSON تولیدشده در dry-run که دامنه دقیق عملیات apply را مشخص می‌کند.",
        )

    def handle(self, *args, **options):
        # Assignment services use Django's default connection. Keep the command's
        # database scope explicit rather than pretending non-default aliases work.
        self.database = "default"
        self.db = connection

        if options["apply"]:
            if not options["plan_file"] or options["plan_out"]:
                raise CommandError(
                    "برای apply فقط --plan-file لازم است؛ --plan-out را استفاده نکنید."
                )
            self._apply_plan(options["plan_file"])
            return

        if options["plan_file"]:
            raise CommandError("--plan-file فقط همراه --apply قابل استفاده است.")

        plan = self._build_plan()
        self._print_plan(plan)

        if options["plan_out"]:
            path = Path(options["plan_out"]).expanduser()
            if path.exists():
                raise CommandError(
                    f"فایل طرح از قبل وجود دارد و بازنویسی نمی‌شود: {path}"
                )
            plan["sha256"] = _plan_digest(plan)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"فایل طرح ذخیره شد: {path} | SHA-256: {plan['sha256']}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "برای apply آینده، dry-run را با --plan-out اجرا کنید؛ "
                    "بدون فایل طرح امکان apply وجود ندارد."
                )
            )

    def _database_identity(self):
        settings = self.db.settings_dict
        return {
            "alias": self.database,
            "name": str(settings.get("NAME") or ""),
            "host": str(settings.get("HOST") or ""),
            "port": str(settings.get("PORT") or ""),
        }

    def _build_plan(self):
        from django.db.models import F

        queryset = (
            WorkflowStepExecution.objects.using(self.database)
            .filter(
                instance__isnull=False,
                instance__status=WorkflowInstance.Status.ACTIVE,
                instance__current_step_id=F("workflow_step_id"),
                is_submitted=False,
                assigned_to__isnull=True,
            )
            .select_related(
                "instance",
                "instance__workflow",
                "workflow_step",
                "workflow_step__workflow",
                "workflow_step__assigned_to",
            )
            .order_by("instance_id", "pk")
        )

        items = []
        for execution in queryset.iterator():
            status, reason, assignee_id = self._assess_candidate(execution)
            items.append({
                "execution_id": execution.pk,
                "instance_id": execution.instance_id,
                "step_id": execution.workflow_step_id,
                "assignee_id": assignee_id,
                "status": status,
                "reason": reason,
            })

        return {
            "version": PLAN_VERSION,
            "created_at": timezone.now().isoformat(),
            "database": self._database_identity(),
            "items": items,
        }

    def _assess_candidate(self, execution):
        instance = execution.instance
        step = execution.workflow_step

        if instance.workflow_id != step.workflow_id:
            return "SKIP", "مرحله و نمونه متعلق به یک گردش‌کار نیستند.", None
        if not instance.workflow.is_active:
            return "SKIP", "گردش‌کار غیرفعال است.", None
        if not step.is_active:
            return "SKIP", "مرحله غیرفعال است.", None
        if step.assignment_policy != WorkflowStep.AssignmentPolicy.FIXED:
            return "SKIP", "سیاست تخصیص مرحله FIXED نیست.", None
        if step.assigned_to_id is None:
            return "SKIP", "برای مرحله مسئول ثابت تعریف نشده است.", None

        open_ids = list(
            WorkflowStepExecution.objects.using(self.database)
            .filter(
                instance_id=instance.pk,
                workflow_step_id=step.pk,
                is_submitted=False,
            )
            .order_by("pk")
            .values_list("pk", flat=True)[:2]
        )
        if len(open_ids) != 1 or open_ids[0] != execution.pk:
            return (
                "SKIP",
                "برای مرحله فعلی دقیقاً یک اجرای باز وجود ندارد؛ نیازمند بررسی دستی.",
                None,
            )

        try:
            WorkflowStepAssignmentService.validate_assignee(
                workflow=step.workflow,
                step=step,
                assignee=step.assigned_to,
            )
        except ValidationError as exc:
            return "SKIP", "مسئول ثابت واجد شرایط نیست: " + "; ".join(exc.messages), None

        return "ELIGIBLE", "واجد شرایط؛ تخصیص از سیاست FIXED بازیابی می‌شود.", step.assigned_to_id

    def _print_plan(self, plan):
        eligible = [item for item in plan["items"] if item["status"] == "ELIGIBLE"]
        skipped = [item for item in plan["items"] if item["status"] == "SKIP"]

        self.stdout.write("")
        self.stdout.write("گزارش repair_missing_step_assignments")
        self.stdout.write(f"Database: {plan['database']}")
        self.stdout.write(f"نامزدهای بررسی‌شده: {len(plan['items'])}")
        self.stdout.write(self.style.SUCCESS(f"واجد شرایط: {len(eligible)}"))
        self.stdout.write(self.style.WARNING(f"ردشده/نیازمند بررسی: {len(skipped)}"))
        self.stdout.write("")
        self.stdout.write("وضعیت | Execution | Instance | Step | Assignee | علت")
        for item in plan["items"]:
            self.stdout.write(
                f"{item['status']} | {item['execution_id']} | "
                f"{item['instance_id']} | {item['step_id']} | "
                f"{item['assignee_id'] or '—'} | {item['reason']}"
            )

    def _load_plan(self, path_value):
        path = Path(path_value).expanduser()
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"خواندن فایل طرح ممکن نیست: {exc}") from exc

        if not isinstance(plan, dict) or plan.get("version") != PLAN_VERSION:
            raise CommandError("نسخه یا ساختار فایل طرح معتبر نیست.")
        supplied_digest = plan.get("sha256")
        if not isinstance(supplied_digest, str) or not hmac.compare_digest(
            supplied_digest,
            _plan_digest(plan),
        ):
            raise CommandError("SHA-256 فایل طرح معتبر نیست؛ فایل تغییر کرده یا خراب است.")
        if plan.get("database") != self._database_identity():
            raise CommandError(
                "هویت دیتابیس با دیتابیسی که dry-run روی آن اجرا شده یکسان نیست."
            )
        if not isinstance(plan.get("items"), list):
            raise CommandError("فهرست نامزدهای فایل طرح معتبر نیست.")
        return plan

    def _apply_plan(self, plan_path):
        plan = self._load_plan(plan_path)
        approved = [item for item in plan["items"] if item.get("status") == "ELIGIBLE"]

        applied = 0
        skipped = 0
        self.stdout.write(
            f"نامزدهای تأییدشده در فایل طرح: {len(approved)}؛ "
            "موارد جدیدی خارج از این فایل اسکن یا اصلاح نمی‌شوند."
        )

        for item in approved:
            result, detail = self._apply_one(item)
            if result == "APPLIED":
                applied += 1
                self.stdout.write(self.style.SUCCESS(
                    f"APPLIED execution={item['execution_id']} "
                    f"instance={item['instance_id']} assignee={item['assignee_id']}"
                ))
            else:
                skipped += 1
                self.stdout.write(self.style.WARNING(
                    f"SKIPPED execution={item.get('execution_id')}: {detail}"
                ))

        self.stdout.write("")
        self.stdout.write(
            f"نتیجه نهایی: اصلاح‌شده={applied} | ردشده به علت تغییر وضعیت/اعتبارسنجی={skipped}"
        )

    def _apply_one(self, item):
        required = ("execution_id", "instance_id", "step_id", "assignee_id")
        if any(key not in item or item[key] is None for key in required):
            return "SKIPPED", "اطلاعات نامزد در فایل طرح ناقص است."

        try:
            with transaction.atomic(using=self.database):
                try:
                    instance = (
                        WorkflowInstance.objects.using(self.database)
                        .select_for_update()
                        .get(pk=item["instance_id"])
                    )
                    execution = (
                        WorkflowStepExecution.objects.using(self.database)
                        .select_for_update()
                        .get(pk=item["execution_id"])
                    )
                    step = (
                        WorkflowStep.objects.using(self.database)
                        .select_for_update()
                        .select_related("workflow", "assigned_to")
                        .get(pk=item["step_id"])
                    )
                except (
                    WorkflowInstance.DoesNotExist,
                    WorkflowStepExecution.DoesNotExist,
                    WorkflowStep.DoesNotExist,
                ):
                    return "SKIPPED", "یکی از رکوردهای طرح دیگر وجود ندارد."

                if execution.instance_id != instance.pk:
                    return "SKIPPED", "اجرای ثبت‌شده دیگر متعلق به این نمونه نیست."
                if execution.workflow_step_id != step.pk:
                    return "SKIPPED", "مرحله اجرای ثبت‌شده تغییر کرده است."
                if instance.status != WorkflowInstance.Status.ACTIVE:
                    return "SKIPPED", "نمونه دیگر ACTIVE نیست."
                if instance.current_step_id != step.pk:
                    return "SKIPPED", "مرحله دیگر مرحله فعلی نمونه نیست."
                if execution.is_submitted:
                    return "SKIPPED", "اجرا در این فاصله ارسال شده است."
                if execution.assigned_to_id is not None:
                    return "SKIPPED", "اجرا در این فاصله مسئول گرفته است."
                if instance.workflow_id != step.workflow_id:
                    return "SKIPPED", "نمونه و مرحله دیگر متعلق به یک گردش‌کار نیستند."
                if not instance.workflow.is_active or not step.is_active:
                    return "SKIPPED", "گردش‌کار یا مرحله غیرفعال شده است."
                if step.assignment_policy != WorkflowStep.AssignmentPolicy.FIXED:
                    return "SKIPPED", "سیاست تخصیص مرحله تغییر کرده است."
                if step.assigned_to_id != item["assignee_id"]:
                    return "SKIPPED", "مسئول ثابت مرحله از زمان dry-run تغییر کرده است."

                open_ids = list(
                    WorkflowStepExecution.objects.using(self.database)
                    .select_for_update()
                    .filter(
                        instance_id=instance.pk,
                        workflow_step_id=step.pk,
                        is_submitted=False,
                    )
                    .order_by("pk")
                    .values_list("pk", flat=True)[:2]
                )
                if len(open_ids) != 1 or open_ids[0] != execution.pk:
                    return "SKIPPED", (
                        "دیگر دقیقاً یک اجرای باز برای مرحله فعلی وجود ندارد."
                    )

                assignee = step.assigned_to
                try:
                    WorkflowStepAssignmentService.validate_assignee(
                        workflow=instance.workflow,
                        step=step,
                        assignee=assignee,
                    )
                    WorkflowStepAssignmentService.assign_execution(
                        execution=execution,
                        assignee=assignee,
                        changed_by=None,
                        source=WorkflowStepAssignmentHistory.Source.POLICY,
                        reason=REPAIR_REASON,
                    )
                except ValidationError as exc:
                    return "SKIPPED", "; ".join(exc.messages)

                return "APPLIED", "تخصیص با سرویس رسمی انجام شد."
        except Exception:
            # Unexpected database/programming errors must abort the command.
            raise
