document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("form[data-instance-id]");
    if (!form) return;

    form.enctype = "multipart/form-data";
    form.encoding = "multipart/form-data";

    const instanceId = form.dataset.instanceId;
    const stepId = form.dataset.stepId || "";
    const shareUrl = form.dataset.shareUrl || "";
    const pendingAcceptanceId = form.dataset.pendingAcceptanceId || "";
    const endpoint = new URL("file-field-definitions/", form.action);
    if (pendingAcceptanceId) {
        endpoint.searchParams.set("pending_acceptance_id", pendingAcceptanceId);
    }

    function cssEscape(value) {
        return window.CSS && CSS.escape
            ? CSS.escape(value)
            : String(value).replace(/(["\\])/g, "\\$1");
    }

    function getCookie(name) {
        const cookies = document.cookie ? document.cookie.split("; ") : [];
        for (const cookie of cookies) {
            const [key, ...parts] = cookie.trim().split("=");
            if (key === name) return decodeURIComponent(parts.join("="));
        }
        return "";
    }

    const shareDraftStates = new Map();

    function shareDialog(field, file) {
        if (!shareUrl || !stepId || !file || !file.id) return;
        const existing = document.getElementById("df-file-share-dialog");
        if (existing) existing.remove();

        const state = shareDraftStates.get(String(file.id)) || {
            recipientIds: [],
            interactionType: "VIEW",
            subject: "",
            body: "",
            view: "edit",
        };
        shareDraftStates.set(String(file.id), state);

        const overlay = document.createElement("div");
        overlay.id = "df-file-share-dialog";
        overlay.className = "df-share-overlay";
        const dialog = document.createElement("section");
        dialog.className = "df-share-dialog";
        dialog.setAttribute("role", "dialog");
        dialog.setAttribute("aria-modal", "true");
        dialog.setAttribute("aria-labelledby", "df-share-title");

        const heading = document.createElement("h2");
        heading.id = "df-share-title";
        heading.textContent = "اشتراک‌گذاری فایل";
        const fileLabel = document.createElement("p");
        fileLabel.className = "df-share-file-name";
        fileLabel.textContent = field.label + " — " + file.name;

        const editor = document.createElement("div");
        editor.className = "df-share-editor";
        const recipientLabel = document.createElement("label");
        recipientLabel.textContent = "گیرندگان";
        const recipientList = document.createElement("div");
        recipientList.className = "df-share-recipient-list";
        recipientList.textContent = "در حال دریافت اعضای فرآیند...";
        const typeLabel = document.createElement("label");
        typeLabel.textContent = "نوع تعامل";
        const type = document.createElement("select");
        [
            ["VIEW", "اشتراک‌گذاری برای مشاهده"],
            ["RESPONSE", "درخواست پاسخ یا دریافت اطلاعات"],
            ["ACTION", "درخواست انجام اقدام"],
            ["REVIEW", "درخواست بررسی یا تأیید فایل"],
        ].forEach(([value, label]) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            type.appendChild(option);
        });
        type.value = state.interactionType || "VIEW";

        const subjectLabel = document.createElement("label");
        subjectLabel.textContent = "موضوع";
        const subject = document.createElement("input");
        subject.type = "text";
        subject.maxLength = 200;
        subject.placeholder = "موضوع پیام (اختیاری)";
        subject.value = state.subject || "";

        const bodyLabel = document.createElement("label");
        bodyLabel.textContent = "توضیحات";
        const body = document.createElement("textarea");
        body.rows = 3;
        body.placeholder = "توضیحات یا درخواست خود را بنویسید...";
        body.value = state.body || "";

        const feedback = document.createElement("div");
        feedback.className = "df-share-feedback";
        const preview = document.createElement("div");
        preview.className = "df-share-preview";
        preview.hidden = true;
        const actions = document.createElement("div");
        actions.className = "df-share-actions";
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "df-button df-button-secondary";
        cancel.textContent = "بستن";
        cancel.addEventListener("click", () => overlay.remove());
        const review = document.createElement("button");
        review.type = "button";
        review.className = "df-button df-button-primary";
        review.textContent = "بررسی و تأیید";
        const back = document.createElement("button");
        back.type = "button";
        back.className = "df-button df-button-secondary";
        back.textContent = "بازگشت و ویرایش";
        back.hidden = true;
        const submit = document.createElement("button");
        submit.type = "button";
        submit.className = "df-button df-button-primary";
        submit.textContent = "تأیید و ثبت پیش‌نویس";
        submit.hidden = true;
        actions.append(cancel, review, back, submit);
        editor.append(recipientLabel, recipientList, typeLabel, type,
            subjectLabel, subject, bodyLabel, body);
        dialog.append(heading, fileLabel, editor, preview, feedback, actions);
        overlay.appendChild(dialog);
        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) overlay.remove();
        });
        document.body.appendChild(overlay);

        function saveState() {
            state.interactionType = type.value;
            state.subject = subject.value;
            state.body = body.value;
        }
        [type, subject, body].forEach((control) => {
            control.addEventListener("input", saveState);
            control.addEventListener("change", saveState);
        });
        recipientList.addEventListener("change", (event) => {
            if (event.target.matches('input[type="checkbox"]')) {
                state.recipientIds = Array.from(
                    recipientList.querySelectorAll('input[type="checkbox"]:checked')
                ).map((input) => Number(input.value));
            }
        });

        function selectedRecipients() {
            return Array.from(
                recipientList.querySelectorAll('input[type="checkbox"]:checked')
            ).map((input) => ({
                id: Number(input.value),
                label: input.parentElement.querySelector("span")?.textContent || "",
            }));
        }
        function showEditor() {
            saveState();
            state.view = "edit";
            editor.hidden = false;
            preview.hidden = true;
            review.hidden = false;
            back.hidden = true;
            submit.hidden = true;
            feedback.textContent = "";
        }
        function showPreview() {
            saveState();
            const recipients = selectedRecipients();
            if (!recipients.length) {
                feedback.textContent = "حداقل یک گیرنده انتخاب کنید.";
                return;
            }
            state.recipientIds = recipients.map((recipient) => recipient.id);
            state.view = "preview";
            const title = document.createElement("h3");
            title.textContent = "خلاصه اشتراک‌گذاری";
            const summary = document.createElement("dl");
            summary.className = "df-share-preview-list";
            const addSummary = (label, value) => {
                const row = document.createElement("div");
                const term = document.createElement("dt");
                term.textContent = label;
                const description = document.createElement("dd");
                description.textContent = value || "—";
                row.append(term, description);
                summary.appendChild(row);
            };
            addSummary("فایل", field.label + " — " + file.name);
            addSummary("گیرندگان", recipients.map((recipient) => recipient.label).join("، "));
            addSummary("نوع تعامل", type.options[type.selectedIndex]?.textContent || type.value);
            addSummary("موضوع", subject.value.trim());
            addSummary("توضیحات", body.value.trim());
            const notice = document.createElement("p");
            notice.className = "df-share-preview-notice";
            notice.textContent = "با تأیید، پیش‌نویس مستقلی برای هر گیرنده ثبت می‌شود. پیام‌ها پس از ارسال فرم نهایی خواهند شد.";
            preview.replaceChildren(title, summary, notice);
            editor.hidden = true;
            preview.hidden = false;
            review.hidden = true;
            back.hidden = false;
            submit.hidden = false;
            feedback.textContent = "";
        }
        review.addEventListener("click", showPreview);
        back.addEventListener("click", showEditor);

        fetch(
            shareUrl + "?instance_id=" + encodeURIComponent(instanceId) +
            "&step_id=" + encodeURIComponent(stepId) +
            "&form_file_id=" + encodeURIComponent(file.id),
            {
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
            }
        ).then(async (response) => {
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "دریافت گیرندگان ناموفق بود.");
            recipientList.replaceChildren();
            const savedDrafts = payload.file_drafts || [];
            if (!state.loadedFromServer) {
                if (savedDrafts.length) {
                    state.recipientIds = savedDrafts.map((draft) => Number(draft.recipient_id));
                    state.interactionType = savedDrafts[0].interaction_type || "VIEW";
                    state.subject = savedDrafts[0].subject || "";
                    state.body = savedDrafts[0].body || "";
                } else {
                    state.recipientIds = [];
                    state.interactionType = "VIEW";
                    state.subject = "";
                    state.body = "";
                }
                type.value = state.interactionType;
                subject.value = state.subject;
                body.value = state.body;
                state.loadedFromServer = true;
            }
            renderShareSummary(targetForFile(file), field, file, savedDrafts);
            const recipients = payload.available_recipients || [];
            if (!recipients.length) {
                recipientList.textContent = "عضو دیگری برای دریافت پیام وجود ندارد.";
                review.disabled = true;
                return;
            }
            recipients.forEach((recipient) => {
                const label = document.createElement("label");
                label.className = "df-share-recipient";
                const checkbox = document.createElement("input");
                checkbox.type = "checkbox";
                checkbox.value = recipient.id;
                checkbox.checked = state.recipientIds.includes(Number(recipient.id));
                const name = document.createElement("span");
                name.textContent = recipient.label;
                label.append(checkbox, name);
                recipientList.appendChild(label);
            });
            if (state.view === "preview") showPreview();
        }).catch((error) => {
            recipientList.textContent = error.message;
            review.disabled = true;
        });

        submit.addEventListener("click", async () => {
            saveState();
            const recipientIds = state.recipientIds;
            if (!recipientIds.length) {
                feedback.textContent = "حداقل یک گیرنده انتخاب کنید.";
                showEditor();
                return;
            }
            submit.disabled = true;
            back.disabled = true;
            cancel.disabled = true;
            feedback.textContent = "در حال ثبت پیش‌نویس‌ها...";
            try {
                const response = await fetch(shareUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRFToken": getCookie("csrftoken"),
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json",
                    },
                    body: JSON.stringify({
                        instance_id: Number(instanceId),
                        step_id: Number(stepId),
                        form_file_id: Number(file.id),
                        recipient_ids: recipientIds,
                        interaction_type: state.interactionType,
                        subject: state.subject,
                        body: state.body,
                    }),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || "ثبت اشتراک‌گذاری انجام نشد.");
                state.loadedFromServer = true;
                state.view = "edit";
                const refreshed = await fetch(
                    shareUrl + "?instance_id=" + encodeURIComponent(instanceId) +
                    "&step_id=" + encodeURIComponent(stepId) +
                    "&form_file_id=" + encodeURIComponent(file.id),
                    { credentials: "same-origin", headers: { "Accept": "application/json" } }
                );
                const refreshedPayload = await refreshed.json();
                if (!refreshed.ok) throw new Error(refreshedPayload.error || "بازیابی پیش‌نویس‌ها ناموفق بود.");
                renderShareSummary(targetForFile(file), field, file, refreshedPayload.file_drafts || []);
                feedback.textContent = "پیش‌نویس‌ها ثبت شدند و در کنار فایل قابل مشاهده و ویرایش هستند.";
                submit.textContent = "ثبت شد";
                window.setTimeout(() => overlay.remove(), 900);
            } catch (error) {
                feedback.textContent = error.message || "خطا در ثبت اشتراک‌گذاری.";
                submit.disabled = false;
                back.disabled = false;
                cancel.disabled = false;
            }
        });
    }

    function targetForFile(file) {
        return form.querySelector('[data-file-share-id="' + cssEscape(String(file.id)) + '"]');
    }

    function renderShareSummary(target, field, file, drafts) {
        if (!target) return;
        const oldSummary = target.querySelector(".df-file-share-summary");
        if (oldSummary) oldSummary.remove();
        if (!drafts || !drafts.length) return;
        const summary = document.createElement("div");
        summary.className = "df-file-share-summary";
        const heading = document.createElement("strong");
        heading.textContent = "پیش‌نویس اشتراک‌گذاری این فایل";
        const recipients = document.createElement("p");
        recipients.textContent = "گیرندگان: " + drafts.map((draft) => draft.recipient).join("، ");
        const labels = { VIEW: "مشاهده", RESPONSE: "درخواست پاسخ", ACTION: "درخواست اقدام", REVIEW: "بررسی و تأیید" };
        const interaction = document.createElement("p");
        interaction.textContent = "نوع تعامل: " + (labels[drafts[0].interaction_type] || drafts[0].interaction_type);
        summary.append(heading, recipients, interaction);
        if (drafts[0].subject) {
            const item = document.createElement("p");
            item.textContent = "موضوع: " + drafts[0].subject;
            summary.appendChild(item);
        }
        if (drafts[0].body) {
            const item = document.createElement("p");
            item.textContent = "توضیحات: " + drafts[0].body;
            summary.appendChild(item);
        }
        const note = document.createElement("small");
        note.textContent = "این موارد پیش‌نویس هستند و پس از ارسال فرم نهایی می‌شوند.";
        summary.appendChild(note);
        target.appendChild(summary);
    }

    function addShareButton(target, field, file) {
        if (!target || !file || !field.shareable || !file.id || target.querySelector(".df-file-share")) return;
        target.dataset.fileShareId = String(file.id);
        const button = document.createElement("button");
        button.type = "button";
        button.className = "df-button df-button-secondary df-file-share";
        button.textContent = "اشتراک‌گذاری";
        button.addEventListener("click", () => shareDialog(field, file));
        target.appendChild(button);
        fetch(
            shareUrl + "?instance_id=" + encodeURIComponent(instanceId) +
            "&step_id=" + encodeURIComponent(stepId) +
            "&form_file_id=" + encodeURIComponent(file.id),
            { credentials: "same-origin", headers: { "Accept": "application/json" } }
        ).then(async (response) => {
            const payload = await response.json();
            if (response.ok) renderShareSummary(target, field, file, payload.file_drafts || []);
        }).catch((error) => console.warn("Could not load file share drafts:", error));
    }

    function renderExistingFile(container, file, field) {
        if (!container || !file) return;
        const target = container.querySelector(".df-form-value, .df-table-value") || container;
        if (target.dataset.fileRendered !== "1") {
            target.replaceChildren();
            const link = document.createElement("a");
            link.href = file.url;
            link.textContent = file.name;
            link.target = "_blank";
            link.rel = "noopener";
            target.appendChild(link);
            target.dataset.fileRendered = "1";
        }
        addShareButton(target, field, file);
    }

    async function deleteFile(file, wrapper, input) {
        if (!file || !file.delete_url || !wrapper) return;

        if (!window.confirm("آیا از حذف این فایل مطمئن هستید؟")) return;

        const button = wrapper.querySelector(".df-file-delete");
        if (button) {
            button.disabled = true;
            button.textContent = "در حال حذف...";
        }

        try {
            const response = await fetch(file.delete_url, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": getCookie("csrftoken"),
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
            });

            let payload = {};
            try {
                payload = await response.json();
            } catch (_) {
                // Keep the generic error below when the server did not return JSON.
            }

            if (!response.ok || !payload.success) {
                throw new Error(payload.error || "حذف فایل انجام نشد.");
            }

            const current = wrapper.querySelector(".df-file-current");
            if (current) current.remove();

            if (input) {
                input.value = "";
                input.required = false;
            }

            wrapper.dataset.fileId = "";
            wrapper.dataset.fileDeleted = "1";
        } catch (error) {
            window.alert(error.message || "حذف فایل انجام نشد.");
            if (button) {
                button.disabled = false;
                button.textContent = "حذف فایل";
            }
        }
    }

    function addFileControl(container, field, file) {
        if (!container) return;

        if (!field.editable) {
            renderExistingFile(container, file, field);
            return;
        }

        const selector = `input[type="file"][data-file-field="${cssEscape(field.code)}"]`;
        const existingInput = container.querySelector(selector);
        if (existingInput) return;

        const input = document.createElement("input");
        input.type = "file";
        input.name = field.input_name;
        input.className = "df-file-input";
        input.dataset.fileField = field.code;
        if (field.required && !file) input.required = true;

        const wrapper = document.createElement("div");
        wrapper.className = "df-file-control";
        wrapper.appendChild(input);

        if (file) {
            const current = document.createElement("div");
            current.className = "df-file-current";

            const link = document.createElement("a");
            link.href = file.url;
            link.textContent = file.name;
            link.target = "_blank";
            link.rel = "noopener";
            current.appendChild(link);

            const note = document.createElement("span");
            note.className = "df-file-current-note";
            note.textContent = " (فایل فعلی؛ برای تعویض فایل جدید انتخاب کنید)";
            current.appendChild(note);

            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "df-file-delete";
            deleteButton.classList.add("df-button", "df-button-danger");
            deleteButton.textContent = "حذف فایل";
            deleteButton.addEventListener("click", () => {
                deleteFile(file, wrapper, input);
            });
            current.appendChild(deleteButton);

            addShareButton(current, field, file);
            wrapper.appendChild(current);
            wrapper.dataset.fileId = String(file.id || "");
        }

        container.appendChild(wrapper);
    }

    function getFormFieldContainer(code) {
        return form.querySelector(
            `.df-form-fields > .df-form-field[data-field-code="${cssEscape(code)}"]`
        );
    }

    function getDirectRepeatableItems(group) {
        return Array.from(group.children).filter(
            (item) =>
                item.matches("[data-repeatable-item]") &&
                !item.hasAttribute("data-repeatable-template")
        );
    }

    function getDirectChildGroups(row) {
        return Array.from(row.querySelectorAll("[data-repeatable-group]")).filter(
            (group) => group.closest("[data-repeatable-item]") === row
        );
    }

    function getGroupOwnedElements(item, group, selector) {
        return Array.from(item.querySelectorAll(selector)).filter(
            (element) => element.closest(".df-repeatable-group") === group
        );
    }

    function getRowId(row, groupPrefix) {
        const idInput = getGroupOwnedElements(
            row,
            row.closest(".df-repeatable-group"),
            "input[type=\"hidden\"]"
        ).find(
            (input) => input.name === `${groupPrefix}__id`
        );
        return idInput ? String(idInput.value || "") : "";
    }

    async function loadDefinitions() {
        try {
            const response = await fetch(
                `${endpoint.toString()}${endpoint.search ? "&" : "?"}instance_id=${encodeURIComponent(instanceId)}`,
                { headers: { "X-Requested-With": "XMLHttpRequest" } }
            );
            if (!response.ok) return;

            const payload = await response.json();

            for (const field of payload.fields || []) {
                if (field.scope !== "FORM") continue;
                const container = getFormFieldContainer(field.code);
                addFileControl(container, field, field.file || null);
            }

            const definitionsByCode = new Map(
                (payload.groups || []).map((group) => [group.code, group])
            );

            const processGroup = (groupElement, parentContext = []) => {
                const groupCode = groupElement.dataset.repeatableGroup;
                const group = definitionsByCode.get(groupCode);
                if (!group) return;

                const rows = getDirectRepeatableItems(groupElement);
                rows.forEach((row, rowIndex) => {
                    const context = [
                        ...parentContext,
                        { groupCode, index: rowIndex },
                    ];
                    const groupPrefix = context
                        .map(({ groupCode: code, index }) => `${code}_${index}_`)
                        .join("");
                    const rowId = getRowId(row, groupPrefix);

                    for (const field of group.fields || []) {
                        const fieldFile = (group.files || []).find(
                            (item) =>
                                item.row_id === rowId &&
                                item.field_code === field.code
                        );
                        const rowField = {
                            ...field,
                            input_name: `${groupPrefix}${field.code}`,
                        };

                        if (group.is_table) {
                            const columnIndex = Number(field.column_index);
                            if (Number.isInteger(columnIndex)) {
                                const cell = row.children[columnIndex];
                                if (cell) {
                                    addFileControl(
                                        cell,
                                        rowField,
                                        fieldFile || null
                                    );
                                }
                            }
                        } else {
                            const container = getGroupOwnedElements(
                                row,
                                groupElement,
                                `.df-form-field[data-field-code="${cssEscape(field.code)}"]`
                            )[0];
                            addFileControl(
                                container,
                                rowField,
                                fieldFile || null
                            );
                        }
                    }

                    for (const childGroup of getDirectChildGroups(row)) {
                        processGroup(childGroup, context);
                    }
                });
            };

            const rootGroups = Array.from(
                form.querySelectorAll("[data-repeatable-group]")
            ).filter(
                (group) => !group.closest("[data-repeatable-item]")
            );
            rootGroups.forEach((group) => processGroup(group));
        } catch (error) {
            console.warn("Workflow file fields could not be loaded:", error);
        }
    }

    loadDefinitions();

    let refreshTimer = null;
    const observer = new MutationObserver(() => {
        window.clearTimeout(refreshTimer);
        refreshTimer = window.setTimeout(loadDefinitions, 0);
    });
    observer.observe(form, { childList: true, subtree: true });
});
