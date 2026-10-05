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
            .querySelectorAll(".inline-related")
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
            .querySelectorAll(".inline-related")
            .forEach(bindRow);

        document.addEventListener("formset:added", function (event) {
            if (event.target) {
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
