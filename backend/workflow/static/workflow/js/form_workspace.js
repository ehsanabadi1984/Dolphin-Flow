(function () {
    "use strict";

    function closestRow(element) {
        if (!element) return null;
        return element.closest(".form-row, .form-group, p") || element.parentElement;
    }

    function setVisible(id, visible) {
        const element = document.getElementById(id);
        const row = closestRow(element);
        if (row) row.hidden = !visible;
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
        clearSelect("id_choice_model");
        clearSelect("id_choice_static_set");
        clearSelect("id_choice_lookup_list");
        clearSelect("id_choice_label_field");
        clearSelect("id_choice_value_field");
        clearSelect("id_choice_parent_field");
        clearSelect("id_choice_filter_field");
    }

    function addOption(select, value, label) {
        if (!select) return;
        select.add(new Option(label, value));
    }

    async function loadModelFields(modelId) {
        const label = document.getElementById("id_choice_label_field");
        const value = document.getElementById("id_choice_value_field");
        const filter = document.getElementById("id_choice_filter_field");

        [label, value, filter].forEach(function (select) {
            if (select) select.replaceChildren(new Option("---------", ""));
        });

        if (!modelId) return;

        try {
            const url = new URL("/admin/workflow/dynamic/formfield-model-fields/", window.location.origin);
            url.searchParams.set("content_type", modelId);
            const response = await fetch(url.toString(), {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (!response.ok) return;

            const data = await response.json();
            const fields = Array.isArray(data.fields) ? data.fields : [];

            fields.forEach(function (field) {
                const text = field.label ? `${field.name} (${field.label})` : field.name;
                addOption(label, field.name, text);
                addOption(value, field.name, text);
                if (field.is_foreign_key) {
                    const filterText = field.related_model
                        ? `${field.name} → ${field.related_model}`
                        : text;
                    addOption(filter, field.name, filterText);
                }
            });
        } catch (error) {
            console.warn("Form Designer: unable to load model fields", error);
        }
    }

    function sync() {
        const type = document.getElementById("id_field_type");
        const source = document.getElementById("id_choice_source");
        if (!type) return;

        const isSelect = type.value === "SELECT";
        const isFormula = type.value === "FORMULA";

        setVisible("id_system_key", !isSelect && !isFormula);
        setVisible("id_is_required", !isFormula);
        setVisible("id_is_history_enabled", !isFormula);
        setVisible("id_choice_source", isSelect);

        [
            "id_choice_model",
            "id_choice_static_set",
            "id_choice_lookup_list",
            "id_choice_label_field",
            "id_choice_value_field",
            "id_choice_parent_field",
            "id_choice_filter_field",
        ].forEach(function (id) { setVisible(id, false); });

        setVisible("id_formula_builder", isFormula);
        setVisible("id_formula_decimal_places", isFormula);

        if (!isSelect) {
            setDisabled("id_choice_source", true);
            clearChoiceConfiguration(false);
            return;
        }

        setDisabled("id_choice_source", false);
        if (!source) return;

        const selectedSource = source.value;
        const isModel = ["MODEL", "SYSTEM_MODEL"].includes(selectedSource);
        const isStatic = ["STATIC", "STATIC_SET"].includes(selectedSource);
        const isLookup = ["LOOKUP", "LOOKUP_LIST"].includes(selectedSource);

        if (isModel) {
            setVisible("id_choice_model", true);
            setVisible("id_choice_label_field", true);
            setVisible("id_choice_value_field", true);
            setVisible("id_choice_parent_field", true);
            setVisible("id_choice_filter_field", true);
            setDisabled("id_choice_model", false);
        } else if (isStatic) {
            setVisible("id_choice_static_set", true);
        } else if (isLookup) {
            setVisible("id_choice_lookup_list", true);
            setVisible("id_choice_parent_field", true);
        }
    }

    function init() {
        const form = document.getElementById("field-properties");
        if (!form) return;

        const type = document.getElementById("id_field_type");
        const source = document.getElementById("id_choice_source");
        const model = document.getElementById("id_choice_model");

        type?.addEventListener("change", function () {
            if (type.value !== "SELECT") clearChoiceConfiguration(false);
            sync();
        });

        source?.addEventListener("change", function () {
            clearChoiceConfiguration(true);
            sync();
            if (["MODEL", "SYSTEM_MODEL"].includes(source.value) && model?.value) {
                loadModelFields(model.value);
            }
        });

        model?.addEventListener("change", function () {
            loadModelFields(model.value);
        });

        sync();
        if (model?.value && ["MODEL", "SYSTEM_MODEL"].includes(source?.value)) {
            loadModelFields(model.value);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
}());
