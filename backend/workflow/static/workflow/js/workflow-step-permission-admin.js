(function () {
    "use strict";

    function updateRow(row) {
        const action = row.querySelector(
            'select[name$="-action"]'
        );
        const actionCode = row.querySelector(
            'select[name$="-action_code"]'
        );

        if (!action || !actionCode) {
            return;
        }

        const field = actionCode.closest(".form-row, td, .field-action_code");

        if (!field) {
            return;
        }

        const visible =
            action.value === "STEP_ACTION";

        field.style.display = visible ? "" : "none";

        if (!visible) {
            actionCode.value = "";
        }
    }

    function updateAllRows() {
        document
            .querySelectorAll(
                ".dynamic-workflowsteppermission_set"
            )
            .forEach(updateRow);
    }

    function bindRow(row) {
        const action = row.querySelector(
            'select[name$="-action"]'
        );

        if (!action || action.dataset.stepActionBound === "true") {
            return;
        }

        action.dataset.stepActionBound = "true";
        action.addEventListener("change", function () {
            updateRow(row);
        });

        updateRow(row);
    }

    function setup() {
        updateAllRows();

        document
            .querySelectorAll(
                ".dynamic-workflowsteppermission_set"
            )
            .forEach(bindRow);

        document.addEventListener("formset:added", function (event) {
            if (
                event.detail &&
                event.detail.formsetName ===
                    "workflowsteppermission_set"
            ) {
                bindRow(event.target);
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            setup,
            { once: true }
        );
    } else {
        setup();
    }
})();
