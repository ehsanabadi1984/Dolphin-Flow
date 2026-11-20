# طراحی فنی سیاست مستقل گیرنده اعلان Accept/Reject

- نسخه: 0.1
- تاریخ: 2026-11-20
- سند مبنا: `step-multi-assignee-phase3-execution-integration.md`، بخش 12
- شاخه هدف: `feature/unidentified-device-without-identifier`
- وضعیت: پیش‌نویس طراحی فنی؛ هنوز پیاده‌سازی نشده و پیش از کدنویسی نیازمند تأیید است.

## 1. هدف و محدوده

این سند تصمیم‌های معماری بخش 12 سند فاز سوم را به قرارداد فنی قابل پیاده‌سازی تبدیل می‌کند. دامنه فقط تعیین گیرنده و ارسال اعلان نتیجه ACCEPT/REJECT برای `WorkflowTransitionExecution`های نیازمند پذیرش است.

موارد زیر خارج از دامنه‌اند:
- تغییر سیاست تخصیص مسئول Step یا منطق ایجاد Execution
- بازطراحی عمومی `NotificationService` یا انواع اعلان‌های دیگر
- تغییر مجوزهای ACCEPT/REJECT
- تغییر اعلان‌های انتقال عادی، START، Finish، SLA یا File Sharing
- تغییر رفتار Production

## 2. مقادیر سیاست

برای هر یک از Accept و Reject چهار مقدار مستقل پشتیبانی می‌شود:

| مقدار | قاعده resolve |
|---|---|
| `SOURCE_COMPLETER` | `completed_by` از همان اجرای مبدأ که Transition جاری را ایجاد کرده است |
| `FIXED_USER` | کاربر ثابت مخصوص همان نتیجه که روی Transition تنظیم شده است |
| `RETURN_STEP_ASSIGNEE` | `assigned_to` از Execution مقصد/بازگشت که در همین عملیات ساخته و تخصیص یافته است |
| `WORKFLOW_STARTER` | `WorkflowInstance.started_by` |

`SOURCE_COMPLETER` به معنای actor پذیرنده/ردکننده نیست. در هر دو مسیر باید از همان `previous_execution` دقیق و مرتبط با Transition جاری استفاده شود.

## 3. تغییرات مدل WorkflowTransition

در `backend/workflow/models.py` چهار فیلد اضافه شود:

| فیلد | نوع | مقدار پیش‌فرض |
|---|---|---|
| `accept_notification_policy` | `CharField(max_length=32, choices=...)` | `SOURCE_COMPLETER` |
| `accept_notification_user` | FK nullable به `AUTH_USER_MODEL`، `on_delete=PROTECT` | `NULL` |
| `reject_notification_policy` | `CharField(max_length=32, choices=...)` | `SOURCE_COMPLETER` |
| `reject_notification_user` | FK nullable به `AUTH_USER_MODEL`، `on_delete=PROTECT` | `NULL` |

- گزینه‌های policy با یک enum از نوع `models.TextChoices` تعریف شوند.
- دو فیلد user مستقل‌اند؛ کاربر ثابت Accept نباید به‌صورت ضمنی برای Reject استفاده شود یا برعکس.
- `PROTECT` مانع حذف کاربری می‌شود که در تنظیمات ثابت Transition ارجاع داده شده است؛ غیرفعال‌کردن کاربر همچنان ممکن است و در زمان اجرا کنترل می‌شود.
- migration باید مقدار `SOURCE_COMPLETER` را برای تمام Transitionهای موجود و جدید اعمال کند. هیچ backfill روی داده‌های Execution انجام نمی‌شود.
- برای هر زوج policy/user یک قید سازگاری دیتابیس در نظر گرفته شود: وقتی policy برابر `FIXED_USER` است user باید غیرتهی باشد؛ در سایر policyها user باید تهی باشد.
- هنگام تغییر policy از `FIXED_USER` به گزینه دیگر، فرم مدیریت مقدار user متناظر را پاک کند.

## 4. اعتبارسنجی تنظیمات در پنل مدیریت

در `WorkflowTransitionAdminForm`:

1. اگر policy مربوطه `FIXED_USER` باشد، user متناظر الزامی است.
2. user ثابت باید در زمان ذخیره فعال باشد.
3. اگر policy غیر از `FIXED_USER` باشد، user متناظر باید تهی شود.
4. هیچ شرط عضویت در Workflow یا مجوز `STEP_ACTION / EXECUTE` برای گیرنده ثابت اعمال نمی‌شود؛ این فیلد گیرنده اعلان است، نه مسئول Execution.
5. همین تنظیمات باید در فرم مستقل Transition و `WorkflowTransitionInline` قابل مدیریت باشند.
6. اعتبارسنجی زمان اجرا مستقل از اعتبارسنجی فرم است؛ چون کاربر ممکن است پس از ذخیره تنظیمات غیرفعال شود.

## 5. سرویس تعیین گیرنده

یک سرویس متمرکز و مستقل در `backend/workflow/notification_services.py` تعریف شود؛ برای نمونه:

`WorkflowTransitionNotificationService`

قرارداد پیشنهادی:
- ورودی: `transition`, `transition_execution`, `instance`, `outcome`, `source_execution`, `result_execution`
- خروجی موفق: یک User فعال به‌عنوان recipient
- خروجی ناموفق در resolve: نتیجه ساخت‌یافته شامل `error_code` و توضیح قابل ثبت؛ نه fallback و نه exceptionی که عملیات اصلی را rollback کند.

سرویس باید policy و user متناظر با outcome را انتخاب کند و resolve را مطابق جدول بخش 2 انجام دهد.

کنترل‌های runtime:
- `SOURCE_COMPLETER`: وجود `source_execution` و `completed_by` بررسی شود.
- `FIXED_USER`: وجود user و `is_active=True` بررسی شود.
- `RETURN_STEP_ASSIGNEE`: وجود `result_execution` و `assigned_to` بررسی شود.
- `WORKFLOW_STARTER`: وجود `instance.started_by` و فعال‌بودن آن بررسی شود.
- در هیچ حالتی recipient با actor فعلی، `reject_to_step.assigned_to` یا شخص دیگری جایگزین نشود.

## 6. مدل ثبت خطای تعیین گیرنده

یک مدل مستقل در `backend/workflow/models.py` اضافه شود:

`WorkflowTransitionNotificationIssue`

فیلدهای پیشنهادی:

| فیلد | نوع | کاربرد |
|---|---|---|
| `transition_execution` | FK به `WorkflowTransitionExecution` با `PROTECT` | عملیات Accept/Reject مرتبط |
| `outcome` | CharField با مقادیر ACCEPT/REJECT | نتیجه‌ای که باید اعلان می‌شد |
| `policy` | CharField | سیاستی که resolve آن ناموفق بوده |
| `error_code` | CharField | علت ماشینی و قابل فیلتر |
| `details` | TextField | توضیح قابل فهم برای مدیر |
| `created_at` | DateTimeField با `auto_now_add=True` | زمان ثبت |

- ارجاع به Instance و Transition از طریق `transition_execution` قابل دسترسی است؛ از ذخیره FKهای تکراری و مستعد ناسازگاری خودداری شود.
- خطاها append-only باشند؛ حذف یا بازنویسی خودکار انجام نشود.
- در پنل مدیریت، فهرست فقط‌خواندنی با فیلتر outcome، policy، error_code و بازه زمانی ارائه شود.
- این رکورد «خطای تعیین گیرنده» است، نه یک Notification برای کاربر نهایی.

## 7. ترتیب اجرا در ACCEPT و REJECT

### ACCEPT

1. اعتبارسنجی و resolve مسئول مقصد طبق Assignment Policy فعلی.
2. ساخت Execution مقصد و تخصیص موفق آن.
3. نهایی‌سازی وضعیت Transition به ACCEPTED و تغییر current_step طبق منطق موجود.
4. resolve گیرنده با policy مربوط به Accept؛ `result_execution` همان Execution مقصد است.
5. اگر recipient معتبر بود، ساخت اعلان از طریق `NotificationService.create`.
6. اگر recipient تعیین نشد، ثبت `WorkflowTransitionNotificationIssue` و ادامه موفق عملیات.

### REJECT

1. اعتبارسنجی و resolve مسئول Step بازگشت طبق Assignment Policy فعلی.
2. ساخت Execution بازگشت و تخصیص موفق آن.
3. نهایی‌سازی وضعیت Transition به REJECTED و تغییر current_step طبق منطق موجود.
4. resolve گیرنده با policy مربوط به Reject؛ `result_execution` همان Execution بازگشت است.
5. اگر recipient معتبر بود، ساخت اعلان از طریق `NotificationService.create`.
6. اگر recipient تعیین نشد، ثبت `WorkflowTransitionNotificationIssue` و ادامه موفق عملیات.

در هر دو مسیر، اعلان فقط پس از موفقیت عملیات اصلی ایجاد می‌شود. خطای ایجاد/تخصیص Execution همچنان باید عملیات اصلی را متوقف و transaction را rollback کند.

## 8. رفتار Transaction و خطا

- رکورد `WorkflowTransitionNotificationIssue` باید در همان transaction عملیات ثبت شود تا همراه با موفقیت Accept/Reject پایدار شود.
- عدم تعیین گیرنده به‌تنهایی نباید exception ایجاد کند یا عملیات اصلی را rollback کند.
- اگر ثبت خود رکورد Issue به دلیل خطای دیتابیس شکست بخورد، این یک خطای زیرساختی متفاوت از «گیرنده پیدا نشد» است و باید طبق رفتار خطاهای دیتابیس مدیریت شود؛ نباید آن را به‌عنوان resolve موفق یا اعلان ارسال‌شده گزارش کرد.
- خطاهای ارسال WebSocket/SMS بعد از commit تابع سازوکار فعلی `NotificationService` باقی می‌مانند و در این تغییر بازطراحی نمی‌شوند.

## 9. اتصال به کد فعلی

فایل‌های هدف:
- `backend/workflow/models.py`: enum، فیلدهای Transition، قیدها و مدل Issue
- migration جدید در `backend/workflow/migrations/`
- `backend/workflow/admin.py`: فیلدها، اعتبارسنجی و صفحه مشاهده Issueها
- `backend/workflow/notification_services.py`: سرویس resolve و ساخت اعلان نتیجه
- `backend/workflow/services.py`: جایگزینی دو بلوک فعلی گیرنده در ACCEPT و REJECT با سرویس جدید
- تست‌های هدفمند در `backend/workflow/tests/`

بلوک‌های قدیمی مبتنی بر `reject_to_step.assigned_to` در هر دو مسیر پس از اتصال سرویس جدید حذف شوند.

## 10. ماتریس تست الزامی

برای هر دو outcome، تست‌های زیر لازم‌اند:

1. `SOURCE_COMPLETER` گیرنده را از `completed_by` اجرای مبدأ دقیق می‌گیرد، نه پذیرنده/ردکننده.
2. `FIXED_USER` کاربر مستقل تنظیم‌شده برای همان outcome را می‌گیرد.
3. `RETURN_STEP_ASSIGNEE` مسئول واقعی Execution تازه ایجادشده را می‌گیرد.
4. `WORKFLOW_STARTER` شروع‌کننده Instance را می‌گیرد.
5. user ثابت خالی یا غیرفعال، recipient تولید نمی‌کند و Issue ثبت می‌شود.
6. نبود `completed_by`، `started_by` یا `assigned_to` لازم، Issue ثبت می‌کند و Accept/Reject را rollback نمی‌کند.
7. در خطای resolve هیچ fallback به `reject_to_step.assigned_to` یا actor انجام نمی‌شود.
8. در صورت resolve موفق، فقط یک Notification با recipient درست ایجاد می‌شود.
9. اگر ایجاد یا تخصیص Execution شکست بخورد، نه Notification موفق و نه Issue مربوط به خطای resolve ایجاد نمی‌شود و عملیات اصلی rollback می‌شود.
10. فرم مدیریت الزامات FIXED_USER و پاک‌سازی user در policyهای غیرثابت را رعایت می‌کند.
11. migration، Transitionهای موجود را با دو policy پیش‌فرض `SOURCE_COMPLETER` حفظ/مقداردهی می‌کند.

## 11. ترتیب پیاده‌سازی پیشنهادی

1. مدل‌ها و migration؛ اجرای `makemigrations --check` و تست migration.
2. فرم و پنل مدیریت؛ تست اعتبارسنجی تنظیمات.
3. سرویس resolve و Issue؛ تست مستقل چهار policy و خطاها.
4. اتصال ACCEPT؛ تست هدفمند Accept.
5. اتصال REJECT؛ تست هدفمند Reject.
6. اجرای مجموعه تست‌های مرتبط فاز سوم و بازبینی diff.

هر مرحله باید جداگانه بررسی و تست شود. هیچ deploy یا تغییری روی Production در این کار وجود ندارد.

## 12. مواردی که این سند قطعی می‌کند

- تنظیم مستقل سیاست Accept و Reject در سطح WorkflowTransition.
- پیش‌فرض هر دو `SOURCE_COMPLETER`.
- الزام user فعال برای `FIXED_USER` در زمان ذخیره و زمان اجرا.
- عدم نیاز گیرنده ثابت به عضویت یا EXECUTE.
- ثبت خطای resolve در مدل مستقل و قابل مشاهده در Admin.
- موفق ماندن Accept/Reject در صورت عدم تعیین گیرنده، بدون fallback.
- استفاده مجدد از `NotificationService` موجود و محدود ماندن تغییر به اعلان نتیجه Accept/Reject.
