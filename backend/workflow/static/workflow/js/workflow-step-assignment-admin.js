(function () {
    "use strict";

    function fieldRow(name) {
        const field = document.getElementById("id_" + name);
        return field ? field.closest(".form-row, .form-group") || field.parentElement : null;
    }

    function updateFields() {
        const policy = document.getElementById("id_assignment_policy");
        if (!policy) {
            return;
        }

        const assignedToRow = fieldRow("assigned_to");
        const sourceStepRow = fieldRow("assignment_source_step");

        if (assignedToRow) {
            assignedToRow.style.display =
                policy.value === "FIXED" ? "" : "none";
        }
        if (sourceStepRow) {
            sourceStepRow.style.display =
                policy.value === "STEP_COMPLETER" ? "" : "none";
        }
    }

    function setup() {
        const policy = document.getElementById("id_assignment_policy");
        if (!policy || policy.dataset.assignmentPolicyBound === "true") {
            return;
        }

        policy.dataset.assignmentPolicyBound = "true";
        policy.addEventListener("change", updateFields);
        updateFields();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", setup, { once: true });
    } else {
        setup();
    }
})();
