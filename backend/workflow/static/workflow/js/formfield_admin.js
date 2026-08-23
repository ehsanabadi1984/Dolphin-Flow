document.addEventListener("DOMContentLoaded", () => {
    const model = document.getElementById("id_choice_model");
    const label = document.getElementById("id_choice_label_field");
    const value = document.getElementById("id_choice_value_field");

    if (!model) return;

    async function loadFields() {
        const id = model.value;

        label.innerHTML = '<option value="">---------</option>';
        value.innerHTML = '<option value="">---------</option>';

        if (!id) return;

        const response = await fetch(
            `/admin/workflow/dynamic/formfield-model-fields/?content_type=${id}`
        );

        const data = await response.json();

        value.innerHTML += `<option value="id">id (شناسه)</option>`;

        data.fields.forEach((field) => {
            const text = `${field.name} (${field.label})`;

            label.innerHTML += `<option value="${field.name}">${text}</option>`;
            value.innerHTML += `<option value="${field.name}">${text}</option>`;
        });
    }

    model.addEventListener("change", loadFields);

    if (model.value) {
        loadFields();
    }
});