document.addEventListener("DOMContentLoaded", () => {
    const model = document.getElementById("id_choice_model");
    const label = document.getElementById("id_choice_label_field");
    const value = document.getElementById("id_choice_value_field");
    const filter = document.getElementById("id_choice_filter_field");

    if (!model) return;

    async function loadFields() {
        const id = model.value;

        // مقدارهای ذخیره‌شده قبل از بازسازی options
        const initialLabel = label?.dataset.initialValue || "";
        const initialValue = value?.dataset.initialValue || "";
        const initialFilter = filter?.dataset.initialValue || "";

        if (label) {
            label.innerHTML = '<option value="">---------</option>';
        }

        if (value) {
            value.innerHTML = '<option value="">---------</option>';
        }

        if (filter) {
            filter.innerHTML = '<option value="">---------</option>';
        }

        if (!id) return;

        const response = await fetch(
            `/admin/workflow/dynamic/formfield-model-fields/?content_type=${id}`
        );

        if (!response.ok) {
            console.error("Failed to load model fields:", response.status);
            return;
        }

        const data = await response.json();

        if (value) {
            value.innerHTML +=
                `<option value="id">id (شناسه)</option>`;
        }

        data.fields.forEach((field) => {
            const text = `${field.name} (${field.label})`;

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

    model.addEventListener("change", loadFields);

    if (model.value) {
        loadFields();
    }
});