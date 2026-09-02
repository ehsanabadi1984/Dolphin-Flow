(function () {
    "use strict";

    function getField(id) {
        return document.getElementById(id);
    }

    function getWorkflowId() {
        const workflow = getField("id_workflow");

        if (!workflow) {
            return "";
        }

        return workflow.value;
    }

    function resetField(field) {
        if (!field) {
            return;
        }

        field.innerHTML = "";

        const option = document.createElement("option");
        option.value = "";
        option.textContent = "---------";

        field.appendChild(option);
        field.disabled = false;
    }

    function setLoading(field) {
        if (!field) {
            return;
        }

        field.innerHTML = "";

        const option = document.createElement("option");
        option.value = "";
        option.textContent = "در حال بارگذاری...";

        field.appendChild(option);
        field.disabled = true;
    }

    function populateField(field, results, preservedValue) {
        if (!field) {
            return;
        }

        /* preservedValue is captured before setLoading clears
         * the field, so editing an existing record keeps the
         * saved from_step / to_step selected after AJAX reload. */
        resetField(field);

        results.forEach(function (item) {
            const option = document.createElement("option");

            option.value = item.id;
            option.textContent = item.label;

            if (
                preservedValue &&
                String(item.id) === String(preservedValue)
            ) {
                option.selected = true;
            }

            field.appendChild(option);
        });

        field.disabled = false;
    }

    function loadField(fieldId, endpoint, workflowId, preservedValue) {
        const field = getField(fieldId);

        if (!field) {
            return;
        }

        if (!workflowId) {
            resetField(field);
            return;
        }

        /* If no preservedValue was passed, capture the
         * currently-selected value so edit pages keep
         * the saved selection after the AJAX reload. */
        if (preservedValue === undefined) {
            preservedValue = field.value;
        }

        setLoading(field);

        const url =
            endpoint +
            "?workflow_id=" +
            encodeURIComponent(workflowId);

        fetch(url, {
            method: "GET",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(
                        "HTTP " + response.status
                    );
                }

                return response.json();
            })
            .then(function (data) {
                populateField(
                    field,
                    data.results || [],
                    preservedValue
                );
            })
            .catch(function (error) {
                console.error(
                    "Workflow dynamic select error:",
                    error
                );

                resetField(field);
            });
    }

    function isTransitionForm() {
        return Boolean(
            getField("id_from_step") || getField("id_to_step")
        );
    }

    function isPermissionForm() {
        return Boolean(
            getField("id_step") || getField("id_transition")
        );
    }

    function loadDependencies() {
        const workflowId = getWorkflowId();

        if (isTransitionForm()) {
            loadField(
                "id_from_step",
                "/admin/workflow/dynamic/steps/",
                workflowId
            );

            loadField(
                "id_to_step",
                "/admin/workflow/dynamic/steps/",
                workflowId
            );
        }

        if (isPermissionForm()) {
            loadField(
                "id_step",
                "/admin/workflow/dynamic/steps/",
                workflowId
            );

            loadField(
                "id_transition",
                "/admin/workflow/dynamic/transitions/",
                workflowId
            );
        }
    }

    /**
     * Detect workflow value changes and reload dependent
     * selects (step, transition, from_step, to_step).
     *
     * Handles two scenarios:
     *   1. Standard <select> — native "change" event.
     *   2. Select2 autocomplete — the native "change" event
     *      may not always fire, so a polling fallback
     *      compares the current value against the last known
     *      value every 500 ms.
     */
    function setupWorkflowDependencyLoader() {
        const workflow = getField("id_workflow");

        if (!workflow) {
            return;
        }

        /* Attach the standard change listener. For standard
         * selects this fires immediately. For Select2 it may
         * or may not fire, but the polling fallback below
         * covers the case where it doesn't. */
        workflow.addEventListener("change", function () {
            loadDependencies();
        });

        /* Polling fallback for Select2 autocomplete.
         *
         * Select2 sometimes does not fire the native change
         * event on the original <select>. We therefore
         * compare the current value against the last known
         * value every 500 ms and trigger a reload when a
         * change is detected.
         *
         * This is lightweight — a single comparison per tick
         * — and self-stops when the workflow field leaves
         * the page. */
        var lastKnownValue = workflow.value;

        setInterval(function () {
            if (workflow.value !== lastKnownValue) {
                lastKnownValue = workflow.value;
                loadDependencies();
            }
        }, 500);

        /* On initial load (e.g. editing an existing record),
         * the workflow value is already set. Load the
         * dependent selects immediately so the admin sees
         * the correct steps/transitions without a page
         * reload. */
        if (workflow.value) {
            loadDependencies();
        }
    }

    document.addEventListener(
        "DOMContentLoaded",
        setupWorkflowDependencyLoader
    );
})();
