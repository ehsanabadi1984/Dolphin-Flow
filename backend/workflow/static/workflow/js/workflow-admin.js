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

    function loadField(fieldId, endpoint, workflowId) {
        const field = getField(fieldId);

        if (!field) {
            return;
        }

        if (!workflowId) {
            resetField(field);
            return;
        }

        /* Capture the currently-selected value BEFORE setLoading
         * clears the field, so populateField can re-select it. */
        const preservedValue = field.value;

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
            getField("id_from_step") ||
            getField("id_to_step")
        );
    }

    function isPermissionForm() {
        return Boolean(
            getField("id_step") ||
            getField("id_transition")
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

    function initialize() {
        const workflow = getField("id_workflow");

        if (!workflow) {
            return;
        }

        workflow.addEventListener(
            "change",
            function () {
                loadDependencies();
            }
        );

        /*
         * هنگام Edit نیز Workflow از قبل انتخاب شده است.
         * بنابراین Step و Transition را در همان لحظه load می‌کنیم.
         */
        if (workflow.value) {
            loadDependencies();
        }
    }

    document.addEventListener(
        "DOMContentLoaded",
        initialize
    );
})();