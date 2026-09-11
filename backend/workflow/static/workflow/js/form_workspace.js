(function () {
    "use strict";

    const CHOICE_FIELDS = [
        "id_choice_model",
        "id_choice_static_set",
        "id_choice_lookup_list",
        "id_choice_label_field",
        "id_choice_value_field",
        "id_choice_parent_field",
        "id_choice_filter_field",
    ];

    function installThemeFixes() {
        if (document.getElementById("df-fw-theme-fixes")) return;

        const style = document.createElement("style");
        style.id = "df-fw-theme-fixes";
        style.textContent = `
            .df-fw-tree-item:hover,
            .df-fw-tree-item.selected {
                color: var(--body-fg, #222) !important;
            }
            .df-fw-form select {
                color: var(--body-fg, #222) !important;
                background-color: var(--body-bg, #fff) !important;
            }
            .df-fw-form select option,
            .df-fw-form select option:checked {
                color: var(--body-fg, #222) !important;
                background-color: var(--body-bg, #fff) !important;
            }
        `;
        document.head.appendChild(style);
    }

    function closestRow(element) {
        if (!element) return null;
        return (
            element.closest(".form-row") ||
            element.closest(".form-group") ||
            element.closest("p") ||
            element.parentElement
        );
    }

    function setVisible(id, visible) {
        const element = document.getElementById(id);
        const row = closestRow(element);
        if (!row) return;

        row.hidden = !visible;
        row.style.display = visible ? "" : "none";
    }

    function setDisabled(id, disabled) {
        const element = document.getElementById(id);
        if (element) element.disabled = disabled;
    }

    function clearSelect(id) {
        const element = document.getElementById(id);
        if (!element) return;
        element.value = "";
    }

    function clearChoiceConfiguration(keepSource) {
        if (!keepSource) clearSelect("id_choice_source");
        CHOICE_FIELDS.forEach(clearSelect);
    }

    function addOption(select, value, label) {
        if (!select) return;
        select.add(new Option(label, value));
    }

    async function loadModelFields(modelId) {
        const label = document.getElementById("id_choice_label_field");
        const value = document.getElementById("id_choice_value_field");
        const filter = document.getElementById("id_choice_filter_field");

        const current = {
            label: label?.value || "",
            value: value?.value || "",
            filter: filter?.value || "",
        };

        [label, value, filter].forEach(function (select) {
            if (select) {
                select.replaceChildren(new Option("---------", ""));
            }
        });

        if (!modelId) return;

        try {
            const url = new URL(
                "/admin/workflow/dynamic/formfield-model-fields/",
                window.location.origin
            );
            url.searchParams.set("content_type", modelId);

            const response = await fetch(url.toString(), {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });

            if (!response.ok) {
                console.warn(
                    "Form Designer: model fields endpoint returned",
                    response.status
                );
                return;
            }

            const data = await response.json();
            const fields = Array.isArray(data.fields) ? data.fields : [];

            fields.forEach(function (field) {
                const text = field.label
                    ? `${field.name} (${field.label})`
                    : field.name;

                addOption(label, field.name, text);
                addOption(value, field.name, text);

                if (field.is_foreign_key) {
                    const filterText = field.related_model
                        ? `${field.name} → ${field.related_model}`
                        : text;
                    addOption(filter, field.name, filterText);
                }
            });

            if (current.label && label) label.value = current.label;
            if (current.value && value) value.value = current.value;
            if (current.filter && filter) filter.value = current.filter;
        } catch (error) {
            console.warn(
                "Form Designer: unable to load model fields",
                error
            );
        }
    }

    function syncProperties() {
        const type = document.getElementById("id_field_type");
        const source = document.getElementById("id_choice_source");

        if (!type) return;

        const isSelect = type.value === "SELECT";
        const isFormula = type.value === "FORMULA";

        // Common properties remain visible. Only type-specific properties
        // are controlled here, preventing stale configuration from another type.
        setVisible("id_system_key", !isSelect && !isFormula);
        setVisible("id_is_required", !isFormula);
        setVisible("id_is_history_enabled", !isFormula);

        // Select-only configuration.
        setVisible("id_choice_source", isSelect);
        CHOICE_FIELDS.forEach(function (id) {
            setVisible(id, false);
            setDisabled(id, !isSelect);
        });

        // Formula-only configuration.
        setVisible("id_formula_builder", isFormula);
        setVisible("id_formula_decimal_places", isFormula);
        setDisabled("id_formula_builder", !isFormula);
        setDisabled("id_formula_decimal_places", !isFormula);

        if (!isSelect) {
            setDisabled("id_choice_source", true);
            clearChoiceConfiguration(false);
            return;
        }

        setDisabled("id_choice_source", false);
        if (!source) return;

        const selectedSource = source.value;

        if (selectedSource === "MODEL") {
            setVisible("id_choice_model", true);
            setVisible("id_choice_label_field", true);
            setVisible("id_choice_value_field", true);
            setVisible("id_choice_parent_field", true);
            setVisible("id_choice_filter_field", true);
        } else if (selectedSource === "STATIC") {
            setVisible("id_choice_static_set", true);
        } else if (selectedSource === "LOOKUP") {
            setVisible("id_choice_lookup_list", true);
            setVisible("id_choice_parent_field", true);
        }
    }

    function init() {
        const form = document.getElementById("field-properties");
        if (!form) return;

        installThemeFixes();

        const type = document.getElementById("id_field_type");
        const source = document.getElementById("id_choice_source");
        const model = document.getElementById("id_choice_model");

        type?.addEventListener("change", function () {
            if (type.value !== "SELECT") {
                clearChoiceConfiguration(false);
            }
            syncProperties();
        });

        source?.addEventListener("change", function () {
            clearChoiceConfiguration(true);
            syncProperties();

            if (source.value === "MODEL" && model?.value) {
                loadModelFields(model.value);
            }
        });

        model?.addEventListener("change", function () {
            if (source?.value === "MODEL") {
                loadModelFields(model.value);
            }
        });

        syncProperties();

        if (source?.value === "MODEL" && model?.value) {
            loadModelFields(model.value);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
}());
