/*
 * Device rows use the workflow form's global edit mode.
 *
 * There is intentionally no per-row edit/save/cancel state.
 * Existing rows expose only the fields the server marked editable;
 * new rows created from the add-device modal are submitted with the
 * main workflow form.
 */
(function () {
    "use strict";

    const isEditMode = () => {
        const form = document.querySelector("form[data-instance-id]");
        return !!form && form.dataset.editMode === "1";
    };

    const activateExistingRows = () => {
        if (!isEditMode()) return;

        document.querySelectorAll("[data-device-row]").forEach((row) => {
            row.querySelectorAll(".df-device-editor").forEach((editor) => {
                editor.hidden = false;
            });

            row.querySelectorAll(".df-device-display").forEach((display) => {
                display.hidden = true;
            });

            // The old per-row controls must not survive in the DOM.
            row.querySelectorAll(
                ".df-device-edit, .df-device-cancel, .df-device-save"
            ).forEach((button) => button.remove());
        });
    };

    const copyModalField = (field, groupCode, index) => {
        const fieldCode = field.dataset.fieldCode;
        if (!fieldCode) return null;

        const input = field.cloneNode(true);
        input.removeAttribute("data-device-modal-field");
        input.classList.add("df-device-generated-field");
        input.disabled = false;
        input.name = `${groupCode}_${index}_${fieldCode}`;

        if (field.tagName === "SELECT") {
            input.value = field.value;
        } else if (field.type === "checkbox") {
            input.checked = field.checked;
        } else {
            input.value = field.value;
        }

        return input;
    };

    const createDeleteButton = () => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "df-button df-button-danger df-device-delete";
        button.textContent = "حذف";
        return button;
    };

    const addDeviceRow = (modal, groupCode) => {
        const form = document.querySelector(".workflow-instance form");
        if (!form || !isEditMode()) return;

        const tbody = form.querySelector(
            `.df-device-table-body[data-group-code="${groupCode}"]`
        );
        if (!tbody) return;

        const rows = tbody.querySelectorAll("[data-device-row]");
        const index = rows.length;

        const row = document.createElement("tr");
        row.className = "df-device-row";
        row.dataset.deviceRow = "";
        row.dataset.deviceIndex = String(index);

        const instanceDeviceId = document.createElement("input");
        instanceDeviceId.type = "hidden";
        instanceDeviceId.name = `${groupCode}_${index}_instance_device_id`;
        instanceDeviceId.value = "";

        modal.querySelectorAll("[data-device-modal-field]").forEach((field) => {
            const cell = document.createElement("td");
            const input = copyModalField(field, groupCode, index);
            if (!input) return;
            cell.appendChild(input);
            row.appendChild(cell);
        });

        const actionsCell = document.createElement("td");
        actionsCell.className = "df-device-actions";
        actionsCell.appendChild(instanceDeviceId);
        actionsCell.appendChild(createDeleteButton());
        row.appendChild(actionsCell);

        const emptyRow = tbody.querySelector(".df-device-empty");
        if (emptyRow) emptyRow.remove();

        tbody.appendChild(row);
    };

    // app.js has not reached DOMContentLoaded yet, so apply the global
    // edit state now and avoid a visible frame with legacy row controls.
    activateExistingRows();

    /*
     * The legacy app.js also listens for .df-device-modal-submit.
     * Capture this event before its bubbling listener so it cannot create
     * the old per-row edit/save/cancel controls.
     */
    document.addEventListener(
        "click",
        (event) => {
            const submitButton = event.target.closest(
                ".df-device-modal-submit"
            );
            if (!submitButton) return;

            if (!isEditMode()) return;

            const modal = submitButton.closest(".df-device-modal");
            if (!modal) return;

            event.preventDefault();
            event.stopImmediatePropagation();

            const fields = modal.querySelectorAll("[data-device-modal-field]");
            let firstInvalid = null;

            fields.forEach((field) => {
                const wrapper = field.closest(".df-device-modal-field");
                const required = wrapper && wrapper.querySelector("label span");
                if (!required) return;

                if (!String(field.value || "").trim()) {
                    wrapper.classList.add("has-error");
                    const error = wrapper.querySelector(".df-device-modal-error");
                    if (error) error.textContent = "این فیلد الزامی است.";
                    if (!firstInvalid) firstInvalid = field;
                }
            });

            if (firstInvalid) {
                firstInvalid.focus();
                return;
            }

            addDeviceRow(modal, submitButton.dataset.groupCode);
            modal.hidden = true;
            document.body.classList.remove("df-modal-open");
        },
        true
    );

    /*
     * Keep deletion inside the global edit session.
     *
     * The legacy delete button submits directly to delete_device. That
     * endpoint performs the deletion and redirects back without ?edit=1,
     * so _get_edit_mode() correctly sees the redirected page as read-only.
     * Intercept the delete click here, perform the POST ourselves, and then
     * explicitly reload the instance with ?edit=1.
     */
    document.addEventListener(
        "click",
        async (event) => {
            const deleteButton = event.target.closest(".df-device-delete");
            if (!deleteButton) return;
            if (!isEditMode()) return;

            const row = deleteButton.closest("[data-device-row]");
            if (!row) return;

            event.preventDefault();
            event.stopImmediatePropagation();

            if (!window.confirm("آیا از حذف این دستگاه از فرآیند مطمئن هستید؟")) {
                return;
            }

            const instanceDeviceId = row.querySelector(
                'input[name$="_instance_device_id"]'
            )?.value;

            // New, unsaved rows only need to disappear from the current form.
            if (!instanceDeviceId) {
                row.remove();
                return;
            }

            const form = deleteButton.closest("form");
            const csrfToken = form?.querySelector(
                'input[name="csrfmiddlewaretoken"]'
            )?.value;
            const deleteUrl = deleteButton.formAction || deleteButton.getAttribute("formaction");

            if (!csrfToken || !deleteUrl) {
                console.error("Unable to delete device: missing CSRF token or delete URL.");
                return;
            }

            try {
                const response = await fetch(deleteUrl, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": csrfToken,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    credentials: "same-origin",
                    redirect: "follow",
                });

                if (!response.ok) {
                    throw new Error(`Delete request failed with status ${response.status}`);
                }

                const url = new URL(window.location.href);
                url.search = "?edit=1";
                window.location.assign(url.toString());
            } catch (error) {
                console.error("Device deletion failed:", error);
                window.alert("حذف دستگاه انجام نشد. لطفاً دوباره تلاش کنید.");
            }
        },
        true
    );
})();