document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("form[data-instance-id]");
    if (!form) return;

    form.enctype = "multipart/form-data";
    form.encoding = "multipart/form-data";

    const instanceId = form.dataset.instanceId;
    const endpoint = new URL("file-field-definitions/", form.action).toString();

    function cssEscape(value) {
        return window.CSS && CSS.escape
            ? CSS.escape(value)
            : String(value).replace(/(["\\])/g, "\\$1");
    }

    function renderExistingFile(container, file) {
        if (!container || !file) return;
        const target = container.querySelector(".df-form-value, .df-table-value") || container;
        if (target.dataset.fileRendered === "1") return;

        target.replaceChildren();
        const link = document.createElement("a");
        link.href = file.url;
        link.textContent = file.name;
        link.target = "_blank";
        link.rel = "noopener";
        target.appendChild(link);
        target.dataset.fileRendered = "1";
    }

    function addFileControl(container, field, file) {
        if (!container) return;

        if (!field.editable) {
            renderExistingFile(container, file);
            return;
        }

        const selector = `input[type="file"][data-file-field="${cssEscape(field.code)}"]`;
        if (container.querySelector(selector)) return;

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
            note.textContent = " (فایل فعلی؛ برای تعویض فایل جدید انتخاب کنید)";
            current.appendChild(note);
            wrapper.appendChild(current);
        }

        container.appendChild(wrapper);
    }

    function getFormFieldContainer(code) {
        return form.querySelector(
            `.df-form-fields > .df-form-field[data-field-code="${cssEscape(code)}"]`
        );
    }

    function getGroupItems(groupCode) {
        const group = form.querySelector(
            `[data-repeatable-group="${cssEscape(groupCode)}"]`
        );
        if (!group) return [];
        return Array.from(group.querySelectorAll("[data-repeatable-item]"));
    }

    function getRowId(groupCode, row, rowIndex) {
        const idInput = row.querySelector(
            `input[type="hidden"][name="${cssEscape(groupCode)}_${rowIndex}__id"]`
        );
        return idInput ? String(idInput.value || "") : "";
    }

    async function loadDefinitions() {
        try {
            const response = await fetch(
                `${endpoint}?instance_id=${encodeURIComponent(instanceId)}`,
                { headers: { "X-Requested-With": "XMLHttpRequest" } }
            );
            if (!response.ok) return;

            const payload = await response.json();

            for (const field of payload.fields || []) {
                if (field.scope !== "FORM") continue;
                const container = getFormFieldContainer(field.code);
                addFileControl(container, field, field.file || null);
            }

            for (const group of payload.groups || []) {
                const rows = getGroupItems(group.code).filter(
                    row => !row.hasAttribute("data-repeatable-template")
                );

                rows.forEach((row, rowIndex) => {
                    const rowId = getRowId(group.code, row, rowIndex);
                    for (const field of group.fields || []) {
                        const fieldFile = (group.files || []).find(
                            item => item.row_id === rowId && item.field_code === field.code
                        );
                        const rowField = {
                            ...field,
                            input_name: `${group.code}_${rowIndex}_${field.code}`,
                        };

                        if (group.is_table) {
                            const columnIndex = Number(field.column_index);
                            if (Number.isInteger(columnIndex)) {
                                const cell = row.children[columnIndex];
                                if (cell) addFileControl(cell, rowField, fieldFile || null);
                            }
                        } else {
                            const container = row.querySelector(
                                `.df-form-field[data-field-code="${cssEscape(field.code)}"]`
                            );
                            addFileControl(container, rowField, fieldFile || null);
                        }
                    }
                });
            }
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
