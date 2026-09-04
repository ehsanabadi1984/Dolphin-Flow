document.addEventListener("DOMContentLoaded", () => {
    const typeField = document.getElementById("id_field_type");
    const sourceField = document.getElementById("id_formula_builder");
    const decimalField = document.getElementById("id_formula_decimal_places");

    if (!typeField || !sourceField || !decimalField) return;

    const fieldOptions = (() => {
        try {
            return JSON.parse(sourceField.dataset.fieldOptions || "[]");
        } catch (error) {
            console.warn("Invalid formula field options:", error);
            return [];
        }
    })();

    let tokens = [];

    try {
        const initial = JSON.parse(sourceField.value || "{}");
        if (Array.isArray(initial.tokens)) tokens = initial.tokens;
        if (initial.decimal_places !== undefined && !decimalField.value) {
            decimalField.value = initial.decimal_places;
        }
    } catch (error) {
        tokens = [];
    }

    function rowFor(id) {
        const field = document.getElementById(id);
        return field?.closest(".form-row") || field?.closest(".fieldBox");
    }

    const builderRow = rowFor("id_formula_builder");
    if (!builderRow) return;

    const panel = document.createElement("div");
    panel.className = "df-formula-builder";
    panel.innerHTML = `
        <div class="df-formula-toolbar">
            <div class="df-formula-control">
                <label>فیلد</label>
                <select class="df-formula-field-select">
                    <option value="">انتخاب فیلد...</option>
                </select>
                <button type="button" data-add-field>افزودن</button>
            </div>
            <div class="df-formula-control">
                <label>عدد</label>
                <input type="text" class="df-formula-number" inputmode="decimal" placeholder="مثلاً 10" />
                <button type="button" data-add-number>افزودن</button>
            </div>
            <div class="df-formula-operators" aria-label="عملگرها">
                <button type="button" data-operator="+">+</button>
                <button type="button" data-operator="-">−</button>
                <button type="button" data-operator="*">×</button>
                <button type="button" data-operator="/">÷</button>
                <button type="button" data-operator="%">%</button>
                <button type="button" data-paren="(">(</button>
                <button type="button" data-paren=")">)</button>
            </div>
        </div>
        <div class="df-formula-expression" aria-live="polite"></div>
        <div class="df-formula-preview"></div>
    `;

    sourceField.parentElement.appendChild(panel);

    const fieldSelect = panel.querySelector(".df-formula-field-select");
    const numberInput = panel.querySelector(".df-formula-number");
    const expression = panel.querySelector(".df-formula-expression");
    const preview = panel.querySelector(".df-formula-preview");

    fieldOptions.forEach((field) => {
        const option = document.createElement("option");
        option.value = field.id;
        option.textContent = `${field.label} (${field.code})`;
        fieldSelect.appendChild(option);
    });

    function tokenText(token) {
        if (token.type === "field") {
            const field = fieldOptions.find((item) => Number(item.id) === Number(token.field_id));
            return field ? field.label : `#${token.field_id}`;
        }
        if (token.type === "number") return token.value;
        return token.value || "";
    }

    function render() {
        expression.innerHTML = "";
        tokens.forEach((token, index) => {
            const chip = document.createElement("span");
            chip.className = `df-formula-token df-formula-token-${token.type}`;
            chip.textContent = tokenText(token);
            chip.title = "حذف";
            chip.dataset.index = index;
            chip.addEventListener("click", () => {
                tokens.splice(index, 1);
                render();
            });
            expression.appendChild(chip);
        });

        const text = tokens.map(tokenText).join(" ");
        preview.textContent = text
            ? `فرمول: ${text}`
            : "هنوز فرمولی ساخته نشده است.";

        sourceField.value = JSON.stringify({
            version: 1,
            tokens,
            decimal_places: Math.max(0, Math.min(Number(decimalField.value || 0), 6)),
        });
    }

    panel.querySelector("[data-add-field]").addEventListener("click", () => {
        const id = Number(fieldSelect.value);
        if (!id) return;
        tokens.push({ type: "field", field_id: id });
        render();
    });

    panel.querySelector("[data-add-number]").addEventListener("click", () => {
        const value = numberInput.value.trim().replace(/,/g, "");
        if (!value || !/^-?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)) return;
        tokens.push({ type: "number", value });
        numberInput.value = "";
        render();
    });

    panel.querySelectorAll("[data-operator]").forEach((button) => {
        button.addEventListener("click", () => {
            tokens.push({ type: "operator", value: button.dataset.operator });
            render();
        });
    });

    panel.querySelectorAll("[data-paren]").forEach((button) => {
        button.addEventListener("click", () => {
            tokens.push({ type: "paren", value: button.dataset.paren });
            render();
        });
    });

    const controlledIds = [
        "id_choice_source",
        "id_choice_model",
        "id_choice_static_set",
        "id_choice_lookup_list",
        "id_choice_label_field",
        "id_choice_value_field",
        "id_choice_parent_field",
        "id_choice_filter_field",
        "id_system_key",
        "id_is_required",
    ];

    function setRowVisible(id, visible) {
        const row = rowFor(id);
        if (row) row.style.display = visible ? "" : "none";
    }

    function syncVisibility() {
        const isFormula = typeField.value === "FORMULA";
        builderRow.style.display = isFormula ? "" : "none";
        setRowVisible("id_formula_decimal_places", isFormula);

        controlledIds.forEach((id) => setRowVisible(id, !isFormula));

        if (isFormula) {
            const required = document.getElementById("id_is_required");
            if (required) required.checked = false;
        }
    }

    typeField.addEventListener("change", syncVisibility);
    decimalField.addEventListener("input", render);

    render();
    syncVisibility();
});
