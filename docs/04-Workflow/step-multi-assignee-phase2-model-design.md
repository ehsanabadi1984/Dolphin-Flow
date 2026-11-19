# طراحی فنی فاز دوم — مدل و سرویس تخصیص مسئول Step

- نسخه: 0.1
- تاریخ: 2026-11-19
- سند مادر: `step-multi-assignee-design.md` نسخه 1.7
- ممیزی baseline: `step-multi-assignee-phase1-audit.md` نسخه 1.6
- شاخه هدف: `feature/unidentified-device-without-identifier`
- وضعیت: طرح اجرایی اولیه؛ پیش از migration باید زنجیره migration شاخه یکپارچه شود

## 1. هدف فاز

در این فاز، مسئولیت از تعریف WorkflowStep به نوبت واقعی WorkflowStepExecution منتقل می‌شود. هر execution باید یک مسئول اجرایی مشخص داشته باشد و هویت وروددهنده (`entered_by`) و تکمیل‌کننده (`completed_by`) مستقل از `performed_by` باقی بماند. این فاز همچنین قرارداد سیاست تخصیص و ثبت تاریخچه تغییر مسئول را در مدل تثبیت می‌کند.

دامنه این فاز فقط مدل، قواعد اعتبارسنجی و سرویس مرکزی نامزد/تخصیص است. اتصال کامل همه مسیرهای start/transition/accept/reject/override و مصرف‌کنندگان کارتابل، اعلان و SLA در فازهای بعدی سند مادر انجام می‌شود؛ با این حال API سرویس باید از ابتدا برای اتصال اتمیک به آن مسیرها طراحی شود.

## 2. مدل داده هدف

### 2.1 WorkflowStep

فیلد `assigned_to` فعلی حفظ می‌شود و Many-to-Many نمی‌شود. این فیلد صرفاً برای سازگاری با Workflowهای قدیمی و سیاست مسئول ثابت باقی می‌ماند؛ وجود آن به‌تنهایی مجوز یا نامزدی ایجاد نمی‌کند.

فیلدهای جدید پیشنهادی:

| فیلد | نوع | کاربرد |
|---|---|---|
| `assignment_policy` | CharField با choices | سیاست تخصیص این Step |
| `assignment_source_step` | FK nullable به WorkflowStep با `PROTECT` | Step مرجع برای سیاست ارجاع به تکمیل‌کننده آن |

سیاست‌های نسخه اول:

- `FIXED`: استفاده از `WorkflowStep.assigned_to`، مشروط به فعال‌بودن، عضویت و EXECUTE مؤثر.
- `INSTANCE_STARTER`: استفاده از `WorkflowInstance.started_by`، مشروط به واجدشرایط بودن.
- `STEP_COMPLETER`: استفاده از `completed_by` اجرای آخر Step مرجع پیکربندی‌شده.
- `PREVIOUS_COMPLETER_SELECTS`: تکمیل‌کننده اجرای مبدأ هنگام انتقال، یک نامزد معتبر مقصد را انتخاب می‌کند.
- `AUTO_SINGLE`: فقط اگر دقیقاً یک نامزد واجدشرایط باشد تخصیص خودکار انجام می‌شود؛ صفر یا چند نامزد باعث توقف با خطای روشن می‌شود.

برای `STEP_COMPLETER`، وجود `assignment_source_step` الزامی و تعلق آن به همان Workflow الزامی است. برای سایر سیاست‌ها این فیلد باید خالی باشد، مگر آنکه در نسخه بعدی تصمیم مستند دیگری ثبت شود.

### 2.2 WorkflowStepExecution

فیلدهای فعلی از جمله `performed_by`, `performed_at`, `is_submitted` و `submitted_at` حفظ می‌شوند. معنای `performed_by` تغییر نمی‌کند و داده‌های قدیمی از روی آن به‌صورت حدسی بازنویسی نمی‌شوند.

فیلدهای جدید پیشنهادی:

| فیلد | نوع | کاربرد |
|---|---|---|
| `assigned_to` | FK nullable به User با `PROTECT` | مسئول منتخب همین نوبت اجرا |
| `entered_by` | FK nullable به User با `PROTECT` | actorی که ورود به این نوبت را ایجاد کرده است |
| `completed_by` | FK nullable به User با `PROTECT` | کاربری که Submit موفق این نوبت را انجام داده است |
| `assigned_at` | DateTime nullable | زمان تخصیص مسئول این نوبت |

`submitted_at` زمان تکمیل/ارسال باقی می‌ماند و از افزودن timestamp تکراری `completed_at` خودداری می‌شود. `performed_at` زمان ایجاد/ورود رکورد را نگه می‌دارد.

برای رکوردهای تاریخی، فیلدهای جدید nullable می‌مانند. هیچ data migration نباید `completed_by` را از `performed_by` یا `FormData.submitted_by` حدس بزند. مقداردهی `entered_by` برای رکوردهای قدیمی نیز فقط در صورت وجود مدرک قطعی در مسیر تولید آن رکورد مجاز است؛ در غیر این صورت NULL حفظ می‌شود.

### 2.3 تاریخچه تخصیص

مدل جدید `WorkflowStepAssignmentHistory` با حداقل فیلدهای زیر ایجاد می‌شود:

- `step_execution` با FK به WorkflowStepExecution و `PROTECT`
- `previous_assignee` و `new_assignee` با FK nullable به User و `PROTECT`
- `changed_by` با FK nullable به User و `PROTECT`
- `source` با choices مشخص مانند INITIAL, POLICY, MANUAL, ACCEPTANCE, OVERRIDE
- `reason` اختیاری
- `created_at` با `auto_now_add=True`

هر تخصیص اولیه و هر تغییر مسئول باید در همان transaction تغییر execution یک ردیف تاریخچه ایجاد کند. تاریخچه append-only است؛ سرویس‌های برنامه نباید ردیف‌های قبلی را ویرایش یا حذف کنند. قید یکتایی یا قاعده idempotency برای جلوگیری از ثبت تکراری یک تخصیص در یک عملیات باید در سرویس اعمال شود.

## 3. قرارداد سرویس مرکزی

سرویس تخصیص باید عملیات مستقل و قابل تست ارائه کند:

1. `get_eligible_assignees(workflow, step)`: اعضای فعال Workflow با مجوز مؤثر `STEP_ACTION / EXECUTE` همان Step را از `WorkflowAuthorizationService` استخراج می‌کند؛ منطق مجوز موازی ایجاد نمی‌شود.
2. `resolve_assignee(...)`: سیاست Step را با context اجرای Instance و execution مبدأ ارزیابی می‌کند و یا یک User مشخص برمی‌گرداند یا خطای دامنه‌ای قابل نمایش می‌دهد.
3. `validate_assignee(...)`: فعال‌بودن کاربر، عضویت فعال Workflow، تعلق Step به Workflow و EXECUTE مؤثر را دوباره سمت سرور کنترل می‌کند.
4. `assign_execution(...)`: `assigned_to` و `assigned_at` را در transaction تنظیم و رویداد تاریخچه را ثبت می‌کند؛ اجرای مجدد یکسان نباید تاریخچه تکراری بسازد.

هیچ شناسه assignee ارسالی از UI قابل اعتماد نیست. در سیاست انتخاب دستی، شناسه انتخابی باید با فهرست نامزدهای فعلی مقصد تطبیق داده شود.

## 4. قواعد و invariantها

- هر execution فعال و قابل اقدام باید دقیقاً یک `assigned_to` معتبر داشته باشد.
- هر Instance در هر لحظه حداکثر یک execution فعال برای `current_step` دارد؛ تعیین execution فعال نباید صرفاً به ترتیب timestamp متکی بماند.
- تخصیص، مجوز EXECUTE ایجاد نمی‌کند و مجوزهای FieldAccess/RepeatableGroupAccess را دور نمی‌زند.
- `started_by`, `performed_by`, `entered_by`, `assigned_to` و `completed_by` معانی مستقل دارند.
- تغییر مسئول در همان execution، execution جدید نمی‌سازد؛ ورود مجدد به Step execution جدید می‌سازد.
- انتقال نامعتبر به‌علت نامزد غیرفعال/غیرعضو/فاقد EXECUTE باید با ValidationError روشن متوقف شود؛ fallback تصادفی ممنوع است.
- اجرای pending acceptance مسئول قطعی مقصد نمی‌سازد؛ نهایی‌سازی تخصیص مقصد در مسیر ACCEPT انجام می‌شود.
- `WorkflowStep.assigned_to` به‌تنهایی هرگز مبنای دسترسی یا اثبات EXECUTE نیست.

## 5. سازگاری داده قدیمی

- `performed_by` بدون تغییر باقی می‌ماند.
- `assigned_to`, `entered_by`, `completed_by`, `assigned_at` برای رکوردهای قبلی NULL می‌مانند، مگر آنکه backfill با شواهد قطعی و تصمیم مستقل تصویب شود.
- Workflowهای قدیمی تا زمان اتصال کامل مصرف‌کنندگان، باید از مسیر سازگاری کنترل‌شده استفاده کنند؛ خواندن بی‌قیدوشرط فیلد جدید در کارتابل/اعلان/SLA پیش از backfill ممنوع است.
- migration فقط schema را توسعه می‌دهد؛ هیچ Workflow، Step، Instance یا execution تاریخی حذف یا بازنویسی نمی‌شود.

## 6. ترتیب پیاده‌سازی

1. حل زنجیره migration فعلی شاخه و ثبت baseline migration graph.
2. افزودن فیلدهای WorkflowStep و WorkflowStepExecution و مدل تاریخچه تخصیص.
3. تولید و بازبینی migration؛ بررسی `sqlmigrate` و `migrate --plan` در محیط توسعه.
4. پیاده‌سازی سرویس نامزدها، اعتبارسنجی و تخصیص مرکزی، بدون تغییر هنوز در همه مسیرهای اجرا.
5. تست واحد سیاست‌ها، DENY precedence، عضویت، کاربر غیرفعال، source step نامعتبر، انتخاب دستی و idempotency تاریخچه.
6. اتصال start/transition/accept/reject/override در فاز 3 پس از سبز شدن تست‌های مستقل فاز 2.

## 7. مانع فعلی migration

در محیط محلی کاربر فایل untracked با نام `0087_alter_smstemplate_options.py` وجود داشت که فقط گزینه‌های Meta مدل SmsTemplate را تغییر می‌دهد و به `0086_global_file_share_sms_rule` وابسته است. پس از دریافت محتوای دقیق فایل، همان migration بدون تغییر معنایی در شاخه توسعه ثبت شد (commit `fb572a75be53161f5ab382a8b8d1639126a764ab`).

گام لازم در محیط محلی: ابتدا محتوای فایل untracked با نسخه ریموت مقایسه شود؛ اگر byte-for-byte یکسان بود، فایل محلی untracked برداشته و شاخه با fast-forward به‌روز شود تا همان فایل تحت کنترل Git قرار گیرد. اگر متفاوت بود، هیچ‌چیز حذف یا overwrite نشود و اختلاف بررسی شود. تا تأیید همگام‌سازی محلی و یکتایی migration graph، migration بعدی ساخته نمی‌شود.

## 8. وضعیت

- ممیزی و baseline فاز اول: تکمیل و ثبت‌شده در سند ممیزی نسخه 1.6.
- زنجیره Migration شاخه توسعه یکپارچه و graph تا `0087` بررسی شد.
- مدل‌های فاز دوم در `backend/workflow/models.py` اضافه شدند.
- Migration `0088_workflowstep_assignment_policy_and_more` تولید، بازبینی و در محیط توسعه اجرا شد؛ فقط schema را تغییر می‌دهد و داده‌های تاریخی را backfill نمی‌کند.
- Migration `0088` در شاخه توسعه ثبت شد (commit: `15cfc4f4ec3ac6b75c7acc013ef220dc4924d69d`).
- سرویس مرکزی اولیه در `backend/workflow/assignment_services.py` پیاده‌سازی شد:
  - استخراج نامزدها از `WorkflowAuthorizationService` با `STEP_ACTION / EXECUTE`
  - اعتبارسنجی عضویت فعال، فعال‌بودن کاربر و مجوز مؤثر Step
  - resolve پنج سیاست تخصیص
  - تخصیص اتمیک و ثبت تاریخچه با idempotency
- تست‌های مستقل سرویس در `backend/workflow/tests/test_step_assignment_services.py` اضافه شدند.
- کد سرویس و تست‌ها در شاخه توسعه ثبت شده‌اند.
- تست‌های مستقل فاز دوم در محیط محلی اجرا شدند: `workflow.tests.test_step_assignment_services` و `workflow.tests.test_workflow_permission_step_action`؛ هر 29 تست موفق شدند و Django system check نیز بدون خطا بود.
- فاز دوم از نظر مدل، migration، سرویس مرکزی و تست‌های مستقل تکمیل و تأیید شد.
- اتصال مسیرهای start/transition/accept/reject/override و مهاجرت مصرف‌کنندگان کارتابل، اعلان و SLA خارج از دامنه این گام است و به فاز 3 موکول می‌شود.
- هیچ‌یک از مسیرهای اجرایی فعلی هنوز به سرویس جدید متصل نشده‌اند؛ اتصال در فاز 3 انجام می‌شود.
- پیش از شروع فاز 3 باید برنامه اتصال و ترتیب مهاجرت مسیرهای start/transition/accept/reject/override و مصرف‌کنندگان کارتابل، داشبورد، اعلان، SLA و timeline به‌صورت مستقل تدوین و تأیید شود.
