(function () {
    "use strict";

    const CHOICE_FIELDS = [
        "choice_model",
        "choice_static_set",
        "choice_lookup_list",
        "choice_label_field",
        "choice_value_field",
        "choice_parent_field",
        "choice_filter_field",
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
            .df-fw-form select option:checked,
            .df-fw-form select option:hover,
            .df-fw-form select option:focus {
                color: var(--body-fg, #222) !important;
                background-color: var(--body-bg, #fff) !important;
            }
        `;
        document.head.appendChild(style);
    }

    function findInput(form, fieldName) {
        if (!form) return null;
        return (
            form.elements.namedItem(fieldName) ||
            form.querySelector('[id$="' + fieldName + '"]')
        );
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

    function setVisible(element, visible) {
        const row = closestRow(element);
        if (!row) return;

        row.hidden = !visible;
        row.style.display = visible ? "" : "none";
    }

    function setDisabled(element, disabled) {
        if (element) element.disabled = disabled;
    }

    function clearSelect(element) {
        if (!element) return;
        element.value = "";
    }

    function clearChoiceConfiguration(controls, keepSource) {
        if (!keepSource && controls.choice_source) {
            controls.choice_source.value = "NONE";
        }
        CHOICE_FIELDS.forEach(function (name) {
            clearSelect(controls[name]);
        });
    }

    function addOption(select, value, label) {
        if (!select) return;
        select.add(new Option(label, value));
    }

    function createModelFieldsLoader(controls) {
        return async function loadModelFields(modelId) {
            const label = controls.choice_label_field;
            const value = controls.choice_value_field;
            const filter = controls.choice_filter_field;

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
                    "/admin/workflow/form-workspace/model-fields/",
                    window.location.origin
                );
                url.searchParams.set("content_type", modelId);

                const response = await fetch(url.toString(), {
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                });

                if (!response.ok) {
                    console.warn(
                        "Form Designer: Workspace model fields endpoint returned",
                        response.status
                    );
                    return;
                }

                const data = await response.json();
                const fields = Array.isArray(data.fields) ? data.fields : [];

                addOption(value, "id", "id (شناسه)");

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
                    "Form Designer: unable to load Workspace model fields",
                    error
                );
            }
        };
    }

    function createPropertySyncer(controls) {
        return function syncProperties() {
            const type = controls.field_type;
            const source = controls.choice_source;

            if (!type) return;

            const isSelect = type.value === "SELECT";
            const isFormula = type.value === "FORMULA";

            setVisible(controls.system_key, !isFormula);
            setVisible(controls.is_required, !isFormula);
            setVisible(controls.is_history_enabled, !isFormula);

            setVisible(controls.choice_source, isSelect);
            CHOICE_FIELDS.forEach(function (name) {
                setVisible(controls[name], false);
                setDisabled(controls[name], !isSelect);
            });

            setVisible(controls.formula_builder, isFormula);
            setVisible(controls.formula_decimal_places, isFormula);
            setDisabled(controls.formula_builder, !isFormula);
            setDisabled(controls.formula_decimal_places, !isFormula);

            if (!isSelect) {
                // choice_source is a required ModelForm field. Keep it enabled
                // while hidden so its valid NONE value is included in POST.
                setDisabled(controls.choice_source, false);
                clearChoiceConfiguration(controls, false);
                return;
            }

            setDisabled(controls.choice_source, false);
            if (!source) return;

            const selectedSource = source.value;

            if (selectedSource === "MODEL") {
                setVisible(controls.choice_model, true);
                setVisible(controls.choice_label_field, true);
                setVisible(controls.choice_value_field, true);
                setVisible(controls.choice_parent_field, true);
                setVisible(controls.choice_filter_field, true);
            } else if (selectedSource === "STATIC") {
                setVisible(controls.choice_static_set, true);
            } else if (selectedSource === "LOOKUP") {
                setVisible(controls.choice_lookup_list, true);
                setVisible(controls.choice_parent_field, true);
            }
        };
    }

    function init() {
        const forms = Array.from(
            document.querySelectorAll("form.df-fw-form")
        ).filter(function (form) {
            return form.querySelector('[name="field_type"]');
        });
        if (!forms.length) return;

        installThemeFixes();

        forms.forEach(function (form) {
            const controls = {
                field_type: findInput(form, "field_type"),
                choice_source: findInput(form, "choice_source"),
                choice_model: findInput(form, "choice_model"),
                choice_static_set: findInput(form, "choice_static_set"),
                choice_lookup_list: findInput(form, "choice_lookup_list"),
                choice_label_field: findInput(form, "choice_label_field"),
                choice_value_field: findInput(form, "choice_value_field"),
                choice_parent_field: findInput(form, "choice_parent_field"),
                choice_filter_field: findInput(form, "choice_filter_field"),
                system_key: findInput(form, "system_key"),
                is_required: findInput(form, "is_required"),
                is_history_enabled: findInput(form, "is_history_enabled"),
                formula_builder: findInput(form, "formula_builder"),
                formula_decimal_places: findInput(
                    form,
                    "formula_decimal_places"
                ),
            };

            const syncProperties = createPropertySyncer(controls);
            const loadModelFields = createModelFieldsLoader(controls);

            controls.field_type?.addEventListener("change", function () {
                if (controls.field_type.value !== "SELECT") {
                    clearChoiceConfiguration(controls, false);
                }
                syncProperties();
            });

            controls.choice_source?.addEventListener("change", function () {
                clearChoiceConfiguration(controls, true);
                syncProperties();

                if (
                    controls.choice_source.value === "MODEL" &&
                    controls.choice_model?.value
                ) {
                    loadModelFields(controls.choice_model.value);
                }
            });

            controls.choice_model?.addEventListener("change", function () {
                if (controls.choice_source?.value === "MODEL") {
                    loadModelFields(controls.choice_model.value);
                }
            });

            syncProperties();

            if (
                controls.choice_source?.value === "MODEL" &&
                controls.choice_model?.value
            ) {
                loadModelFields(controls.choice_model.value);
            }
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
}());
