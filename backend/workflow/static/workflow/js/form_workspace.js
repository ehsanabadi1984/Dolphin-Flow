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
        if (selectedSource === "MODEL") {
            setVisible("id_choice_model", true);
            setVisible("id_choice_label_field", true);
            setVisible("id_choice_value_field", true);
            setVisible("id_choice_parent_field", true);
            setDisabled("id_choice_model", false);
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

        const type = document.getElementById("id_field_type");
        const source = document.getElementById("id_choice_source");

        type?.addEventListener("change", function () {
            if (type.value !== "SELECT") clearChoiceConfiguration(false);
            sync();
        });

        source?.addEventListener("change", function () {
            clearChoiceConfiguration(true);
            sync();
        });

        sync();
    }

    document.addEventListener("DOMContentLoaded", init);
}());
