document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("form[data-instance-id]");
    if (!form) return;

    form.enctype = "multipart/form-data";
    form.encoding = "multipart/form-data";

    const instanceId = form.dataset.instanceId;
    const endpoint = new URL("file-field-definitions/", form.action).toString();

    function cssEscape(value) {
        return window.CSS && CSS.escape ? CSS.escape(value) : String(value).replace(/(["\\])/g, "\\$1");
    }

    function addFileControl(container, field, file) {
        if (!container || container.querySelector(`input[type="file"][data-file-field="${cssEscape(field.code)}"]`)) {
            return;
        }

        const input = document.createElement("input");
        input.type = "file";
        input.name = field.input_name;
        input.className = "df-file-input";
        input.dataset.fileField = field.code;
        if (field.required) input.required = true;

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
            note.textContent = " (فایل فعلی)";
            current.appendChild(note);
            wrapper.appendChild(current);
        }

        container.appendChild(wrapper);
    }

    function getFormFieldContainer(code) {
        return form.querySelector(`.df-form-fields > .df-form-field[data-field-code="${cssEscape(code)}"]`);
    }

    function getGroupItems(groupCode) {
        const group = form.querySelector(`[data-repeatable-group="${cssEscape(groupCode)}"]`);
        if (!group) return [];
        return Array.from(group.querySelectorAll("[data-repeatable-item]"));
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
                if (field.scope === "FORM") {
                    const container = getFormFieldContainer(field.code);
                    if (!container || !field.editable) continue;
                    addFileControl(container, field, field.file || null);
                }
            }

            for (const group of payload.groups || []) {
                const rows = getGroupItems(group.code);
                const visibleRows = rows.filter(
                    row => !row.hasAttribute("data-repeatable-template")
                );

                visibleRows.forEach((row, rowIndex) => {
                    const rowId = row.dataset.rowId || "";
                    for (const field of group.fields || []) {
                        if (!field.editable) continue;
                        const columnIndex = Number(field.column_index);
                        const fieldFile = (group.files || []).find(
                            item => item.row_id === rowId && item.field_code === field.code
                        );

                        if (Number.isInteger(columnIndex)) {
                            const cell = row.children[columnIndex];
                            if (cell) {
                                addFileControl(cell, {
                                    ...field,
                                    input_name: `${group.code}_${rowIndex}_${field.code}`,
                                }, fieldFile || null);
                            }
                        } else {
                            const container = row.querySelector(
                                `.df-form-field[data-field-code="${cssEscape(field.code)}"]`
                            );
                            if (container) {
                                addFileControl(container, {
                                    ...field,
                                    input_name: `${group.code}_${rowIndex}_${field.code}`,
                                }, fieldFile || null);
                            }
                        }
                    }
                });
            }
        } catch (error) {
            console.warn("Workflow file fields could not be loaded:", error);
        }
    }

    loadDefinitions();

    const observer = new MutationObserver(() => {
        loadDefinitions();
    });
    observer.observe(form, { childList: true, subtree: true });
});
