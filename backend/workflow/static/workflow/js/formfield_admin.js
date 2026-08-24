document.addEventListener("DOMContentLoaded", () => {
    const source = document.getElementById("id_choice_source");

    const model = document.getElementById("id_choice_model");
    const staticSet = document.getElementById("id_choice_static_set");
    const lookupList = document.getElementById("id_choice_lookup_list");

    const label = document.getElementById("id_choice_label_field");
    const value = document.getElementById("id_choice_value_field");
    const parent = document.getElementById("id_choice_parent_field");
    const filter = document.getElementById("id_choice_filter_field");

    // --------------------------------------------------
    // Helpers
    // --------------------------------------------------

    function getFieldRow(field) {
        if (!field) return null;

        return (
            field.closest(".form-row") ||
            field.closest(".fieldBox")
        );
    }

    function setVisible(field, visible) {
        const row = getFieldRow(field);

        if (row) {
            row.style.display = visible ? "" : "none";
        }
    }

    // --------------------------------------------------
    // Choice Source visibility
    // --------------------------------------------------

    function updateChoiceSourceVisibility() {
        if (!source) return;

        const sourceValue = source.value;

        const isModel = sourceValue === "MODEL";
        const isStatic = sourceValue === "STATIC";
        const isLookup = sourceValue === "LOOKUP";

        // Source-specific fields
        setVisible(model, isModel);
        setVisible(staticSet, isStatic);
        setVisible(lookupList, isLookup);

        // Model-only fields
        setVisible(label, isModel);
        setVisible(value, isModel);
        setVisible(parent, isModel);
        setVisible(filter, isModel);
    }

    // --------------------------------------------------
    // Dynamic Model Fields
    // --------------------------------------------------

    async function loadFields() {
        if (!model) return;

        const id = model.value;

        // مقدارهای ذخیره‌شده قبل از بازسازی options
        const initialLabel = label?.dataset.initialValue || "";
        const initialValue = value?.dataset.initialValue || "";
        const initialFilter = filter?.dataset.initialValue || "";

        if (label) {
            label.innerHTML =
                '<option value="">---------</option>';
        }

        if (value) {
            value.innerHTML =
                '<option value="">---------</option>';
        }

        if (filter) {
            filter.innerHTML =
                '<option value="">---------</option>';
        }

        if (!id) {
            return;
        }

        const response = await fetch(
            `/admin/workflow/dynamic/formfield-model-fields/?content_type=${id}`
        );

        if (!response.ok) {
            console.error(
                "Failed to load model fields:",
                response.status
            );
            return;
        }

        const data = await response.json();

        if (value) {
            value.innerHTML +=
                `<option value="id">id (شناسه)</option>`;
        }

        data.fields.forEach((field) => {
            const text =
                `${field.name} (${field.label})`;

            if (label) {
                label.innerHTML +=
                    `<option value="${field.name}">${text}</option>`;
            }

            if (value) {
                value.innerHTML +=
                    `<option value="${field.name}">${text}</option>`;
            }

            // فقط ForeignKeyها برای Filter Field
            if (filter && field.is_foreign_key) {
                filter.innerHTML +=
                    `<option value="${field.name}">${field.name} → ${field.label}</option>`;
            }
        });

        // --------------------------------------------------
        // Restore saved values
        // --------------------------------------------------

        if (label && initialLabel) {
            label.value = initialLabel;
        }

        if (value && initialValue) {
            value.value = initialValue;
        }

        if (filter && initialFilter) {
            filter.value = initialFilter;
        }
    }

    // --------------------------------------------------
    // Events
    // --------------------------------------------------

    if (source) {
        source.addEventListener(
            "change",
            updateChoiceSourceVisibility
        );
    }

    if (model) {
        model.addEventListener(
            "change",
            loadFields
        );
    }

    // --------------------------------------------------
    // Initial state
    // --------------------------------------------------

    updateChoiceSourceVisibility();

    if (model && model.value) {
        loadFields();
    }
});