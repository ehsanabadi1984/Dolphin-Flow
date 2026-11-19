# ممیزی فاز اول و ماتریس رگرسیون چندمسئولی Workflow

- نسخه: 1.5
- تاریخ: 2026-11-19
- سند مبنا: step-multi-assignee-design.md نسخه 1.7
- شاخه: feature/unidentified-device-without-identifier
- وضعیت: ممیزی خواندنی؛ چهار تصمیم معماری تأیید و ثبت شد؛ بدون تغییر کد، migration یا اجرای تست

## 1. نتیجه اجرایی

چندمسئولی‌سازی فقط تغییر مدل WorkflowStepExecution نیست. مسئولیت فعلی Step در کارتابل، اعلان و SLA از WorkflowStep.assigned_to تک‌کاربره خوانده می‌شود؛ مشارکت تاریخی نیز در بعضی مسیرها از WorkflowStepExecution.performed_by استنباط می‌شود. این مصرف‌کنندگان باید به assignment و actorهای مستقل هر نوبت منتقل شوند.

دو نکته کلیدی:
- performed_by در WorkflowStepExecution تکمیل‌کننده فرم نیست؛ در مسیرهای بررسی‌شده actor ایجاد/ورود نوبت را ثبت می‌کند.
- FormData یک‌به‌یک به WorkflowInstance است و نمی‌تواند تکمیل‌کننده چند StepExecution را نگهداری کند. داده canonical در سطح Instance بماند و انتساب هر ارسال در StepExecution ثبت شود.

## 2. نقشه فایل‌های تحت تأثیر

### هسته و مجوز
| فایل | وضعیت فعلی | نیاز تغییر |
|---|---|---|
| backend/workflow/models.py | WorkflowStep.assigned_to تک‌کاربره؛ WorkflowStepExecution دارای performed_by و فاقد assigned_to/entered_by/completed_by | توسعه مدل نوبت و حفظ معنای داده تاریخی |
| backend/workflow/services.py | ایجاد execution در شروع، انتقال، پذیرش و رد پذیرش؛ snapshot هنگام انتقال | یکپارچه‌سازی ایجاد execution و تخصیص |
| backend/workflow/override_services.py | ساخت execution جدید با performed_by مدیر | تفکیک actor اصلاح مسیر از مسئول و تکمیل‌کننده |
| backend/workflow/authorization.py | مجوز مؤثر با عضویت، مجوز مستقیم/نقشی و DENY | استفاده مجدد برای استخراج نامزدهای مسئول |
| backend/workflow/access_matrix.py و access_workspace.py | STEP_ACTIONS شامل VIEW، EXECUTE و MANAGE؛ مجوز Transition مستقل است | حفظ ماتریس فعلی و عدم ساخت سیستم موازی |

### فرم و تاریخچه
| فایل | وضعیت فعلی | نیاز تغییر |
|---|---|---|
| backend/workflow/form_draft_save_services.py | execution آخر Step را بر اساس performed_at می‌گیرد؛ در _save_draft پارامتر user و step کنار گذاشته می‌شوند | execution فعال و مسئول نوبت صریحاً بررسی شود؛ سیاست ثبت ویرایشگر draft تعیین شود |
| backend/workflow/form_draft_normal_field_apply_services.py | فقط FormData.data و updated_at را ذخیره می‌کند | canonical data حفظ شود؛ audit هویت در سطح execution/event قرار گیرد |
| backend/workflow/form_draft_submit_services.py | وضعیت canonical را اعتبارسنجی می‌کند و داده را تغییر نمی‌دهد | نتیجه Submit به execution دقیق و تکمیل‌کننده متصل شود |
| backend/workflow/history_services.py | snapshot از FormData و ردیف‌های تکرارشونده هنگام انتقال می‌سازد | snapshot مستقل و immutable هر execution حفظ شود |
| backend/workflow/history_browser_service.py | snapshot را می‌خواند و HISTORY و Field/Group permissions را اعمال می‌کند | فیلتر completed_by و execution مشخص افزوده شود |
| backend/workflow/form_services.py | فرم را از FormData جاری و ردیف‌های canonical می‌سازد | نمایش تاریخی باید snapshot همان execution را بخواند |
| backend/operator_panel/views.py | انتخاب read context، ذخیره draft و اجرای Transition؛ تابع تاریخی Step برمی‌گرداند نه execution | execution دقیق در تاریخچه انتخاب شود؛ مسئولیت نوشتن و assignee مقصد سمت سرور اعتبارسنجی شود |

### کارتابل، اعلان و SLA
| فایل | وابستگی فعلی | نیاز تغییر |
|---|---|---|
| backend/operator_panel/dashboard_services.py | task، pending، count و timeline به current_step.assigned_to و performed_by متکی‌اند | queryها بر اساس مسئول نوبت جاری و actorهای مستقل بازنویسی شوند |
| backend/operator_panel/dashboard_enhancements.py | waiting-for-others بر اساس started_by و assigned_to ثابت | مسئول execution جاری مبنا باشد |
| backend/operator_panel/process_views.py | assigned_tasks با current_step__assigned_to_id فیلتر می‌کند | فیلتر بر اساس assignment execution جاری |
| backend/workflow/process_summary_services.py | Step خلاصه را با آخرین performed_by=user انتخاب می‌کند | completed_by و execution تکمیل‌شده مبنا قرار گیرد |
| backend/workflow/sla_monitor_services.py | هشدار را به workflow_step.assigned_to می‌فرستد | هشدار به مسئول execution مشخص برسد |
| backend/workflow/acceptance_queue_services.py | صف بر اساس مجوز مؤثر ACCEPT/REJECT است | مستقل از مسئول مقصد بماند؛ تا پذیرش، مقصد کار فعال نشود |
| backend/workflow/notification_services.py | سرویس عمومی ساخت اعلان | حفظ شود؛ recipient در فراخواننده از assignment execution بیاید |

### رابط و مسیرهای جانبی
- backend/operator_panel/templates/operator_panel/workflow_instance.html: فرم Transition فقط شناسه Transition را ارسال می‌کند؛ انتخاب مسئول مقصد در UI وجود ندارد.
- backend/operator_panel/templates/operator_panel/assigned_tasks.html: متن و فهرست وظایف به اختصاص مستقیم Step وابسته است.
- backend/operator_panel/templates/operator_panel/sidebar.html: شمارنده‌ها از DashboardService می‌آیند.
- backend/workflow/form_print_services.py: مجوز چاپ مستقل بماند.
- backend/workflow/file_share_authorization.py و file_share_services.py: مسئولیت Step نباید مجوز Share Files ایجاد کند.

## 3. معنای داده‌های فعلی

### performed_by
در محل‌های بررسی‌شده ایجاد WorkflowStepExecution، performed_by کاربری را ثبت می‌کند که باعث ایجاد نوبت شده است: شروع‌کننده، انتقال‌دهنده، تأییدکننده/ردکننده یا مدیر اصلاح مسیر. این مقدار لزوماً مجری یا تکمیل‌کننده نوبت نیست. معنای تاریخی آن حفظ شود و به completed_by تبدیل یا برای رکوردهای قدیمی حدس زده نشود.

### FormData و submitted_by
FormData یک‌به‌یک به WorkflowInstance متصل است. مسیر ذخیره draft در سرویس اعمال فیلد عادی فقط data و updated_at را ذخیره می‌کند. FormDraftSubmitService اعتبارسنجی می‌کند و ثبت ارسال واقعی در WorkflowStepExecution و snapshot انتقال انجام می‌شود. در مسیرهای بررسی‌شده submitted_by به‌عنوان تکمیل‌کننده هر نوبت مقداردهی نمی‌شود و نباید جایگزین completed_by شود.

### Draft و snapshot
داده فیلدهای عادی در FormData مشترک Instance ذخیره می‌شود و داده گروه‌های تکرارشونده در مدل‌های ردیف/مقدار. _save_draft پس از اعتبارسنجی user و step را کنار می‌گذارد؛ بنابراین ویرایشگر draft در این مسیر ثبت نمی‌شود. snapshot هنگام Submit از داده canonical ساخته می‌شود و برای هر execution جداگانه نگهداری می‌شود. تاریخچه ارسال‌ها قابل تفکیک است، اما تاریخچه تغییرات draft و ویرایشگر هر تغییر در وضعیت فعلی ثبت نمی‌شود.

### تاریخچه و نمایش تاریخی
HistoryBrowserService snapshotهای execution را می‌خواند و مجوز HISTORY و Field/Group را اعمال می‌کند. اما form_services.py داده جاری FormData را می‌خواند. بعضی مسیرهای تاریخی ابتدا Step را انتخاب می‌کنند و سپس فرم را از داده جاری می‌سازند. تابع _get_historical_view_step نیز Step برمی‌گرداند نه execution؛ برای اجرای چندباره یک Step، این روش برای نمایش snapshot دقیق کافی نیست.

## 4. ماتریس تست‌های موجود و تست‌های جدید

| حوزه | پوشش فعلی | تست جدید لازم |
|---|---|---|
| START | workflow/tests/test_start_permission.py: مجوز مستقیم/نقشی، DENY، شروع بدون VIEW/EXECUTE و دسترسی ضمنی شروع‌کننده | دو کاربر مجاز یک Workflow دو Instance مستقل بسازند؛ started_by مستقل باشد |
| EXECUTE و TRANSITION | workflow/tests/test_workflow_execution.py: execute_permission_alone_does_not_authorize_transition، transition_permission_works_without_execute_permission، assigned_to_does_not_grant_transition_permission؛ operator_panel/test_permission_integration.py | نامزدها از EXECUTE مؤثر استخراج شوند؛ Transition همچنان مجوز مستقل بخواهد |
| سیاست تخصیص | پوشش مستقیم ندارد | ثابت، started_by، completed_by یک Step مرجع، انتخاب دستی، تک‌نامزد، چندنامزد و نامزد غیرفعال |
| ایجاد execution | workflow/tests/test_workflow_execution.py و operator_panel/test_pending_acceptance_actions.py | entered_by، assigned_to و completed_by در شروع، انتقال، پذیرش، رد و override تفکیک شوند |
| Draft | workflow/tests/test_form_draft_save_services.py: context، edit mode، submitted step و Field/Group permissions | draft به execution و editor متصل شود؛ دسترسی کاربر غیرمسئول مطابق سیاست نهایی آزموده شود |
| Submit | workflow/tests/test_form_draft_submit_services.py و تست‌های submit در test_workflow_execution.py | completed_by فقط بعد از Submit موفق ثبت شود؛ submit تکراری/هم‌زمان انتساب دوگانه نسازد |
| Snapshot | workflow/tests/test_history_service.py: immutability و چند Transition؛ workflow/tests/test_history_browser.py: HISTORY و فیلتر Field/Group | فیلتر completed_by و نمایش snapshot دقیق execution، حتی برای تکرار یک Step |
| کارتابل | operator_panel/test_dashboard_sidebar.py، test_dashboard_permission_contract.py و test_process_views.py | task و badge فقط برای مسئول execution جاری باشد |
| فرآیندهای شخصی | operator_panel/test_workflow_instance_post.py و test_dashboard_sidebar.py | شروع‌کننده، واردکننده Step، تکمیل‌کننده و سوابق شخصی تفکیک شوند |
| Field/Group | workflow/tests/test_permission_context.py و test_form_draft_save_services.py | assignment هیچ مجوز فیلد/گروه را دور نزند |
| پذیرش | workflow/tests/test_pending_acceptance_queue_service.py، operator_panel/test_pending_acceptance_actions.py و test_pending_acceptance_detail.py | assignment مقصد تا ACCEPT فعال نشود؛ REJECT سیاست مقصد بازگشت را اجرا کند |
| اعلان | workflow/tests/test_workflow_execution.py، test_notification_service.py و test_sla_monitor_service.py | فقط مسئول نهایی همان execution اعلان بگیرد |
| SLA | workflow/tests/test_sla_integration.py، test_sla_lifecycle.py و test_sla_monitor_service.py | هشدار برای مسئول execution جاری؛ تغییر مسئول SLA را reset نکند؛ نوبت جدید SLA جدید داشته باشد |
| Override | workflow/tests/test_workflow_override.py | مدیر اصلاح مسیر با completed_by اشتباه نشود |
| چاپ و فایل | workflow/tests/test_form_print_services.py، test_file_share_authorization.py، test_file_share_drafts.py و test_file_share_response_views.py | assignment به‌تنهایی مجوز چاپ/Share Files ایجاد نکند |
| سازگاری قدیمی | تست‌های فعلی Workflow، انتقال، کارتابل و SLA | migration بدون انتساب ساختگی و حفظ رفتار Workflow تک‌مسئولی |

وجود تست در فهرست به معنی اجرای موفق آن نیست. در این ممیزی فقط فایل‌ها و قرارداد تست بررسی شده‌اند؛ تستی اجرا نشده است. فایل test_workflow_execution_roles.py توابع سطح ماژول دارد و نحوه اجرای آن باید جداگانه بررسی شود.

## 5. ریسک‌های فنی

1. انتخاب آخرین execution در چند محل بر اساس performed_at انجام می‌شود. تشخیص execution فعال باید مرکزی و deterministic باشد و در زمان برابر ترتیب قطعی داشته باشد.
2. ایجاد execution در start، transition، accept، reject و override پراکنده است؛ باید از قواعد مشترک ایجاد/تخصیص استفاده کنند.
3. queryهای کارتابل، badge، timeline و SLA هرکدام assignment را جداگانه محاسبه می‌کنند؛ اصلاح View به‌تنهایی کافی نیست.
4. performed_by در dashboard timeline و ProcessSummary برای مشارکت/انتخاب Step مصرف می‌شود؛ این مصرف‌ها باید با entered_by و completed_by بازتعریف شوند.
5. مسیر ذخیره draft مسئول execution جاری را صریحاً کنترل نمی‌کند؛ PermissionContext عمدتاً Field/Group permissions را می‌سنجد.
6. شناسه assignee ارسالی از UI قابل اعتماد نیست و باید سمت سرور با نامزدهای مجاز همان Step اعتبارسنجی شود.
7. در Transition نیازمند پذیرش، انتخاب مقصد باید موقت بماند و تا ACCEPT کار فعال و اعلان نهایی ایجاد نشود.
8. حفظ assigned_to قدیمی بدون مهاجرت کارتابل، اعلان و SLA رفتار متناقض می‌سازد.
9. تاریخچه باید execution محور باشد؛ Step به‌تنهایی هویت نوبت را مشخص نمی‌کند.
10. completed_by نباید خودکار مجوز مشاهده کل Instance یا مراحل دیگر را ایجاد کند.

## 6. تصمیم‌های لازم پیش از فاز 2

1. **نامزدهای مسئول — تأیید شد:** مدیر Workflow افراد مشخص را در Access & Security موجود با مجوز مستقیم `EXECUTE` همان Step تعیین می‌کند. نامزد باید عضو فعال همان Workflow باشد و مجوز مؤثر `EXECUTE` را داشته باشد. محاسبه باید مجوزهای مستقیم/نقشی و اثر `ALLOW` و `DENY` را مطابق قواعد فعلی لحاظ کند. مجوزهای نقش‌محور ممکن است نامزدهای دیگری نیز ایجاد کنند؛ محدودسازی باید با همان ابزارهای فعلی مجوز و `DENY` انجام شود. سیاست تخصیص از میان نامزدهای مؤثر یک مسئول واقعی برای هر execution تعیین می‌کند. `WorkflowStep.assigned_to` به‌تنهایی نامزدی یا مجوز ایجاد نمی‌کند و فعلاً Many-to-Many نمی‌شود.
2. **شرط ویرایش — تأیید شد:** فقط مسئول منتخب execution فعال مجاز به ویرایش و Submit است؛ مشروط به مجوز مؤثر `EXECUTE` همان Step و رعایت `FieldAccess` و `RepeatableGroupAccess`. مجوز `VIEW` مستقل است و به‌تنهایی اجازه ویرایش یا Submit ایجاد نمی‌کند. این کنترل باید سمت سرور در مسیرهای draft و Submit اعمال شود.
3. **Audit draft — تأیید شد:** هر ذخیره موفق draft، حتی بدون تغییر مقدار فیلدها، یک رویداد ممیزی مستقل و غیرقابل‌تغییر ایجاد می‌کند. رویداد شامل editor/actor، زمان، WorkflowInstance، Step و WorkflowStepExecution دقیق است. داده canonical همچنان در FormData سطح Instance باقی می‌ماند؛ برای هر کاربر یا execution FormData جداگانه ساخته نمی‌شود و ثبت audit به معنی snapshot کامل داده‌ها در هر ذخیره نیست.
4. **مشاهده ثبت شخصی — خارج از دامنه فعلی و غیرمسدودکننده:** در این مرحله تغییری در رفتار فعلی مشاهده سوابق ایجاد نمی‌شود. این موضوع برای طراحی و اجرای چندمسئولیِ فعلی شرط لازم نیست و در صورت نیاز می‌تواند در کار مستقلی بررسی شود.
5. **پذیرش — تأیید شد:** assignee مقصد تا ACCEPT تخصیص موقت است؛ پیش از پذیرش، مسئولیت اجرایی قطعی، وظیفه کارتابل و اعلان `ACTION_REQUIRED` مقصد ایجاد نمی‌شود. پس از ACCEPT تخصیص نهایی و execution مقصد فعال می‌شود. در REJECT، پیش‌فرض بازگشت به Step مبدأ و تکمیل‌کننده اجرای مبدأ (`completed_by`) است و یک execution جدید ایجاد می‌شود؛ مدیر می‌تواند سیاست صریح دیگری برای Transition تعریف کند. اگر تکمیل‌کننده مبدأ نامعتبر باشد، قاعده نامزد نامعتبر اعمال می‌شود و جایگزینی پنهان ممنوع است.
6. **نامزد نامعتبر — تأیید شد:** اگر مسئول حاصل از سیاست تخصیص، از جمله مسئول ثابت یا تکمیل‌کننده Step مرجع، هنگام تخصیص غیرفعال باشد، عضو فعال Workflow نباشد یا مجوز مؤثر `EXECUTE` همان Step را نداشته باشد، انتقال متوقف و علت به‌روشنی اعلام می‌شود. جایگزینی فقط در صورت وجود سیاست جایگزین صریح و ازپیش‌پیکربندی‌شده مجاز است؛ انتخاب پنهانی یا تصادفی مسئول دیگر ممنوع است.

## 7. وضعیت فاز اول

- ممیزی فایل‌ها و وابستگی‌های اصلی: انجام شد.
- نگاشت تست‌های موجود و شکاف‌های تستی: انجام شد.
- اجرای تست‌ها: انجام نشده؛ در این فاز صرفاً inventory و test mapping انجام شده است.
- تصمیم بخش 6، مورد 1 (نامزدهای مسئول و منبع تخصیص): تأیید و در سند مبنا ثبت شد.
- تصمیم بخش 6، مورد 2 (شرط ویرایش و Submit): تأیید و در سند مبنا ثبت شد.
- تصمیم بخش 6، مورد 3 (ثبت ممیزی هر ذخیره موفق draft): تأیید و در سند مبنا ثبت شد.
- تصمیم بخش 6، مورد 5 (انتقال نیازمند پذیرش و رفتار REJECT): تأیید و در سند مبنا ثبت شد.
- تصمیم بخش 6، مورد 4 (مشاهده ثبت شخصی): فعلاً خارج از دامنه و غیرمسدودکننده؛ رفتار موجود بدون تغییر باقی می‌ماند.
- تصمیم بخش 6، مورد 6 (نامزد نامعتبر): تأیید و در سند مبنا ثبت شد.
- فاز 1 (ممیزی و test mapping): تکمیل شد.
- اجرای تست‌های baseline: انجام نشده و باید پیش از آغاز فاز 2 اجرا و نتیجه آن بررسی شود.
- فاز 2 (مدل و migration): تا اجرای موفق و بررسی تست‌های baseline آغاز نشود.
