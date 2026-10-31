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

    function shareDialog(field, file) {
        if (!shareUrl || !stepId || !file || !file.id) return;
        const existing = document.getElementById("df-file-share-dialog");
        if (existing) existing.remove();

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
        const subjectLabel = document.createElement("label");
        subjectLabel.textContent = "موضوع";
        const subject = document.createElement("input");
        subject.type = "text";
        subject.maxLength = 200;
        subject.placeholder = "موضوع پیام (اختیاری)";
        const bodyLabel = document.createElement("label");
        bodyLabel.textContent = "توضیحات";
        const body = document.createElement("textarea");
        body.rows = 3;
        body.placeholder = "توضیحات یا درخواست خود را بنویسید...";
        const feedback = document.createElement("div");
        feedback.className = "df-share-feedback";
        const actions = document.createElement("div");
        actions.className = "df-share-actions";
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "df-button df-button-secondary";
        cancel.textContent = "انصراف";
        cancel.addEventListener("click", () => overlay.remove());
        const submit = document.createElement("button");
        submit.type = "button";
        submit.className = "df-button df-button-primary";
        submit.textContent = "ثبت اشتراک‌گذاری";
        actions.append(cancel, submit);
        dialog.append(heading, fileLabel, recipientLabel, recipientList,
            typeLabel, type, subjectLabel, subject, bodyLabel, body, feedback, actions);
        overlay.appendChild(dialog);
        overlay.addEventListener("click", (event) => {
            if (event.target === overlay) overlay.remove();
        });
        document.body.appendChild(overlay);

        fetch(shareUrl + "?instance_id=" + encodeURIComponent(instanceId), {
            credentials: "same-origin",
            headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
        }).then(async (response) => {
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "دریافت گیرندگان ناموفق بود.");
            recipientList.replaceChildren();
            if (!(payload.available_recipients || []).length) {
                recipientList.textContent = "عضو دیگری برای دریافت پیام وجود ندارد.";
                submit.disabled = true;
                return;
            }
            payload.available_recipients.forEach((recipient) => {
                const label = document.createElement("label");
                label.className = "df-share-recipient";
                const checkbox = document.createElement("input");
                checkbox.type = "checkbox";
                checkbox.value = recipient.id;
                const name = document.createElement("span");
                name.textContent = recipient.label;
                label.append(checkbox, name);
                recipientList.appendChild(label);
            });
        }).catch((error) => {
            recipientList.textContent = error.message;
            submit.disabled = true;
        });

        submit.addEventListener("click", async () => {
            const recipientIds = Array.from(
                recipientList.querySelectorAll('input[type="checkbox"]:checked')
            ).map((input) => Number(input.value));
            if (!recipientIds.length) {
                feedback.textContent = "حداقل یک گیرنده انتخاب کنید.";
                return;
            }
            submit.disabled = true;
            feedback.textContent = "در حال ثبت...";
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
                        interaction_type: type.value,
                        subject: subject.value,
                        body: body.value,
                    }),
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || "ثبت اشتراک‌گذاری انجام نشد.");
                feedback.textContent = "پیش‌نویس اشتراک‌گذاری برای " + payload.draft_ids.length + " گیرنده ثبت شد. پیام‌ها پس از ارسال فرم نهایی می‌شوند.";
                submit.textContent = "ثبت شد";
                window.setTimeout(() => overlay.remove(), 1800);
            } catch (error) {
                feedback.textContent = error.message || "خطا در ثبت اشتراک‌گذاری.";
                submit.disabled = false;
            }
        });
    }

    function addShareButton(target, field, file) {
        if (!target || !file || !field.shareable || !file.id || target.querySelector(".df-file-share")) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "df-button df-button-secondary df-file-share";
        button.textContent = "اشتراک‌گذاری";
        button.addEventListener("click", () => shareDialog(field, file));
        target.appendChild(button);
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
