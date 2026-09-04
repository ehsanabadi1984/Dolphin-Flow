document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("form[data-instance-id]");
    if (!form) return;

    const instanceId = form.dataset.instanceId;
    const endpoint = new URL("formula-definitions/", form.action).toString();

    const state = {
        fieldsById: new Map(),
        formulasById: new Map(),
        loading: false,
    };

    function toNumber(value) {
        if (value === null || value === undefined || value === "") return 0;
        if (typeof value === "string") value = value.trim().replace(/,/g, "");
        const number = Number(value);
        return Number.isFinite(number) ? number : 0;
    }

    function readInput(element) {
        if (!element) return 0;
        if (element.type === "checkbox") return element.checked ? 1 : 0;
        return toNumber(element.value);
    }

    function findNamedElement(name, root = document) {
        const elements = root.querySelectorAll("input, select, textarea");
        for (const element of elements) {
            if (element.name === name) return element;
        }
        return null;
    }

    function evaluateFormula(formula, rowRoot = null, rowIndex = null, stack = new Set()) {
        if (!formula || !Array.isArray(formula.tokens)) return 0;

        const key = `${formula.field_id}:${rowIndex === null ? "form" : rowIndex}`;
        if (stack.has(key)) return 0;
        stack.add(key);

        const output = [];
        const operators = [];
        const precedence = { "+": 1, "-": 1, "*": 2, "/": 2, "%": 2 };

        for (const token of formula.tokens) {
            if (token.type === "number") {
                output.push({ type: "value", value: toNumber(token.value) });
                continue;
            }

            if (token.type === "field") {
                const field = state.fieldsById.get(Number(token.field_id));
                const value = field
                    ? evaluateField(field, formula, rowRoot, rowIndex, stack)
                    : 0;
                output.push({ type: "value", value });
                continue;
            }

            if (token.type === "operator") {
                const current = token.value;
                while (operators.length) {
                    const top = operators[operators.length - 1];
                    if (top.type !== "operator") break;
                    if (precedence[top.value] < precedence[current]) break;
                    output.push(operators.pop());
                }
                operators.push(token);
                continue;
            }

            if (token.type === "paren") {
                if (token.value === "(") {
                    operators.push(token);
                } else {
                    while (operators.length && operators[operators.length - 1].value !== "(") {
                        output.push(operators.pop());
                    }
                    if (operators.length) operators.pop();
                }
            }
        }

        while (operators.length) output.push(operators.pop());

        const values = [];
        for (const token of output) {
            if (token.type === "value") {
                values.push(token.value);
                continue;
            }

            if (values.length < 2) {
                stack.delete(key);
                return 0;
            }

            const right = values.pop();
            const left = values.pop();
            let value = 0;

            if (token.value === "+") value = left + right;
            else if (token.value === "-") value = left - right;
            else if (token.value === "*") value = left * right;
            else if (token.value === "/") value = right === 0 ? 0 : left / right;
            else if (token.value === "%") value = right === 0 ? 0 : left % right;

            values.push(value);
        }

        const result = values.length === 1 ? values[0] : 0;
        stack.delete(key);
        return result;
    }

    function evaluateField(field, ownerFormula, rowRoot, rowIndex, stack) {
        const ownerIsRow = ownerFormula.scope === "ROW";

        if (ownerIsRow && field.group_code !== ownerFormula.group_code) {
            return 0;
        }

        const dependency = state.formulasById.get(Number(field.id));
        if (dependency) {
            return evaluateFormula(dependency, rowRoot, rowIndex, stack);
        }

        const name = ownerIsRow
            ? `${ownerFormula.group_code}_${rowIndex}_${field.code}`
            : field.code;

        return readInput(findNamedElement(name, rowRoot || document));
    }

    function formatNumber(value, decimalPlaces) {
        const places = Math.max(0, Math.min(Number(decimalPlaces) || 0, 6));
        if (!Number.isFinite(value)) return "";
        return value.toLocaleString("en-US", {
            minimumFractionDigits: places,
            maximumFractionDigits: places,
            useGrouping: false,
        });
    }

    function normalizeLabel(value) {
        return String(value || "")
            .replace(/\s+/g, " ")
            .replace(/\s*\*\s*$/, "")
            .trim();
    }

    function getNormalFormulaContainer(formula) {
        const fields = form.querySelectorAll(".df-form-field[data-field-code]");

        // The formula must be rendered into its own field container.
        // Field codes are only guaranteed to be unique inside a section,
        // so matching by code alone can target the neighboring field when
        // two sections happen to reuse the same code.
        for (const field of fields) {
            const label = field.querySelector("label");
            if (normalizeLabel(label?.textContent) === normalizeLabel(formula.label)) {
                return field;
            }
        }

        // Backward-compatible fallback for forms whose label is unavailable.
        for (const field of fields) {
            if (field.dataset.fieldCode === formula.code) return field;
        }

        return null;
    }

    function setNormalFormulaValue(formula, value) {
        const container = getNormalFormulaContainer(formula);
        if (!container) return;

        let output = container.querySelector(".df-formula-value");
        if (!output) {
            output = document.createElement("div");
            output.className = "df-form-value df-formula-value";
            const fallback = container.querySelector(".df-form-value");
            if (fallback) fallback.replaceWith(output);
            else container.appendChild(output);
        }
        output.textContent = formatNumber(value, formula.decimal_places);
    }

    function setRowFormulaValue(formula, row, value) {
        const columns = formula.visible_columns || [];
        const columnIndex = columns.indexOf(formula.code);
        if (columnIndex < 0) return;

        const cell = row.children[columnIndex];
        if (!cell) return;

        let output = cell.querySelector(".df-formula-value");
        if (!output) {
            output = document.createElement("div");
            output.className = "df-table-value df-formula-value";
            cell.replaceChildren(output);
        }
        output.textContent = formatNumber(value, formula.decimal_places);
    }

    function recalculate() {
        for (const formula of state.formulasById.values()) {
            if (formula.scope === "FORM") {
                setNormalFormulaValue(formula, evaluateFormula(formula));
                continue;
            }

            const group = form.querySelector(
                `[data-repeatable-group="${formula.group_code}"]`
            );
            if (!group) continue;

            const rows = group.querySelectorAll(
                "[data-repeatable-item]:not([data-repeatable-template])"
            );

            rows.forEach((row, index) => {
                const value = evaluateFormula(formula, row, index, new Set());

                if (group.classList.contains("df-table-group")) {
                    setRowFormulaValue(formula, row, value);
                } else {
                    let output = row.querySelector(
                        `.df-formula-value[data-formula-id="${formula.field_id}"]`
                    );
                    if (!output) {
                        output = document.createElement("div");
                        output.className = "df-form-value df-formula-value";
                        output.dataset.formulaId = String(formula.field_id);
                        row.appendChild(output);
                    }
                    output.textContent = `${formula.label}: ${formatNumber(value, formula.decimal_places)}`;
                }
            });
        }
    }

    async function loadDefinitions() {
        if (state.loading) return;
        state.loading = true;

        try {
            const response = await fetch(
                `${endpoint}?instance_id=${encodeURIComponent(instanceId)}`,
                {
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                }
            );
            if (!response.ok) return;

            const payload = await response.json();
            state.fieldsById.clear();
            state.formulasById.clear();

            for (const field of payload.fields || []) {
                state.fieldsById.set(Number(field.id), field);
            }

            for (const formula of payload.formulas || []) {
                state.formulasById.set(Number(formula.field_id), formula);
            }

            recalculate();
        } catch (error) {
            console.warn("Formula definitions could not be loaded:", error);
        } finally {
            state.loading = false;
        }
    }

    let recalcTimer = null;
    function scheduleRecalculate() {
        window.clearTimeout(recalcTimer);
        recalcTimer = window.setTimeout(recalculate, 0);
    }

    form.addEventListener("input", scheduleRecalculate);
    form.addEventListener("change", scheduleRecalculate);

    const observer = new MutationObserver(scheduleRecalculate);
    observer.observe(form, { childList: true, subtree: true });

    loadDefinitions();
});
