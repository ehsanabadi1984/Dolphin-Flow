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
                    throw new Error("HTTP " + response.status);
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

    function loadDependencies(preserveValues) {
        const workflowId = getWorkflowId();

        if (isTransitionForm()) {
            const fromStep = getField("id_from_step");
            const toStep = getField("id_to_step");

            loadField(
                "id_from_step",
                "/admin/workflow/dynamic/steps/",
                workflowId,
                preserveValues && fromStep ? fromStep.value : ""
            );

            loadField(
                "id_to_step",
                "/admin/workflow/dynamic/steps/",
                workflowId,
                preserveValues && toStep ? toStep.value : ""
            );
        }

        if (isPermissionForm()) {
            const step = getField("id_step");
            const transition = getField("id_transition");

            loadField(
                "id_step",
                "/admin/workflow/dynamic/steps/",
                workflowId,
                preserveValues && step ? step.value : ""
            );

            loadField(
                "id_transition",
                "/admin/workflow/dynamic/transitions/",
                workflowId,
                preserveValues && transition ? transition.value : ""
            );
        }
    }

    function setupWorkflowDependencyLoader() {
        if (document.body.dataset.workflowDependencyLoaderInitialized === "true") {
            return;
        }

        const workflow = getField("id_workflow");

        if (!workflow) {
            return;
        }

        document.body.dataset.workflowDependencyLoaderInitialized = "true";

        /* Django Admin autocomplete uses Select2, but Select2
         * updates the original <select> and emits a change
         * event. Listening to that event keeps this independent
         * of Select2's internal implementation. */
        workflow.addEventListener("change", function () {
            /* A changed workflow must never retain a step or
             * transition belonging to the previous workflow. */
            loadDependencies(false);
        });

        /* Initial load is needed on edit pages. On add pages
         * there is normally no workflow yet, so this is a no-op. */
        if (workflow.value) {
            loadDependencies(true);
        }
    }

    /* Django Admin can load custom media after DOMContentLoaded.
     * Handle both execution orders so initialization is never
     * skipped. */
    if (document.readyState === "loading") {
        document.addEventListener(
            "DOMContentLoaded",
            setupWorkflowDependencyLoader,
            { once: true }
        );
    } else {
        setupWorkflowDependencyLoader();
    }
})();
