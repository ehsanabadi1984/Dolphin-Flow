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

    const FUNCTIONS = new Set([
        "SUM",
        "ABS",
        "MIN",
        "MAX",
        "AVG",
        "ROUND",
        "FLOOR",
        "CEIL",
    ]);

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

    class TokenParser {
        constructor(tokens, valueResolver) {
            this.tokens = tokens;
            this.valueResolver = valueResolver;
            this.index = 0;
        }

        current() {
            return this.tokens[this.index] || null;
        }

        advance() {
            return this.tokens[this.index++] || null;
        }

        match(type, value = undefined) {
            const token = this.current();
            if (!token || token.type !== type) return false;
            return value === undefined || token.value === value;
        }

        parse() {
            const value = this.parseExpression();
            return this.index === this.tokens.length ? value : 0;
        }

        parseExpression() {
            let value = this.parseTerm();
            while (this.match("operator", "+") || this.match("operator", "-")) {
                const operator = this.advance().value;
                const right = this.parseTerm();
                value = operator === "+" ? value + right : value - right;
            }
            return value;
        }

        parseTerm() {
            let value = this.parseFactor();
            while (
                this.match("operator", "*") ||
                this.match("operator", "/") ||
                this.match("operator", "%")
            ) {
                const operator = this.advance().value;
                const right = this.parseFactor();
                if (operator === "*") value *= right;
                else if (operator === "/") value = right === 0 ? 0 : value / right;
                else value = right === 0 ? 0 : value % right;
            }
            return value;
        }

        parseFactor() {
            const token = this.current();
            if (!token) return 0;

            if (token.type === "number") {
                this.advance();
                return toNumber(token.value);
            }

            if (token.type === "field") {
                this.advance();
                return this.valueResolver(Number(token.field_id));
            }

            if (this.match("paren", "(")) {
                this.advance();
                const value = this.parseExpression();
                if (this.match("paren", ")")) this.advance();
                return value;
            }

            if (token.type === "function") {
                this.advance();
                const name = String(token.value || "").toUpperCase();
                if (!FUNCTIONS.has(name) || !this.match("paren", "(")) return 0;
                this.advance();

                const args = [];
                if (!this.match("paren", ")")) {
                    while (true) {
                        args.push(this.parseExpression());
                        if (this.match("comma")) {
                            this.advance();
                            if (this.match("paren", ")")) return 0;
                            continue;
                        }
                        break;
                    }
                }

                if (!this.match("paren", ")")) return 0;
                this.advance();
                return evaluateFunction(name, args);
            }

            return 0;
        }
    }

    function roundHalfUp(value, places) {
        const factor = 10 ** places;
        const scaled = value * factor;
        const rounded = scaled >= 0
            ? Math.floor(scaled + 0.5)
            : Math.ceil(scaled - 0.5);
        return rounded / factor;
    }

    function evaluateFunction(name, args) {
        if (!args.length) return 0;
        if (name === "SUM") return args.reduce((sum, value) => sum + value, 0);
        if (name === "ABS") return Math.abs(args[0]);
        if (name === "MIN") return Math.min(...args);
        if (name === "MAX") return Math.max(...args);
        if (name === "AVG") {
            return args.reduce((sum, value) => sum + value, 0) / args.length;
        }
        if (name === "ROUND") {
            const places = args.length > 1 ? Math.trunc(args[1]) : 0;
            if (places < 0 || places > 6) return 0;
            return roundHalfUp(args[0], places);
        }
        if (name === "FLOOR") return Math.floor(args[0]);
        if (name === "CEIL") return Math.ceil(args[0]);
        return 0;
    }

    function evaluateFormula(formula, rowRoot = null, rowIndex = null, stack = new Set()) {
        if (!formula || !Array.isArray(formula.tokens)) return 0;

        const key = `${formula.field_id}:${rowIndex === null ? "form" : rowIndex}`;
        if (stack.has(key)) return 0;
        stack.add(key);

        try {
            const parser = new TokenParser(
                formula.tokens,
                (fieldId) => {
                    const field = state.fieldsById.get(Number(fieldId));
                    return field
                        ? evaluateField(field, formula, rowRoot, rowIndex, stack)
                        : 0;
                },
            );
            return parser.parse();
        } finally {
            stack.delete(key);
        }
    }

    function evaluateField(field, ownerFormula, rowRoot, rowIndex, stack) {
        const ownerIsRow = ownerFormula.scope === "ROW";

        if (ownerIsRow && field.group_code !== ownerFormula.group_code) {
            return 0;
        }

        const dependency = state.formulasById.get(Number(field.id));
        if (dependency) {
            if (ownerIsRow && dependency.scope !== "ROW") return 0;
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

    function getNormalFieldContainers() {
        return Array.from(form.querySelectorAll(".df-form-field[data-field-code]"));
    }

    function getNormalFormulaContainer(formula) {
        const containers = getNormalFieldContainers();
        const expectedIndex = Number(formula.dom_index);

        if (Number.isInteger(expectedIndex) && expectedIndex >= 0) {
            const exact = containers[expectedIndex];
            if (exact) return exact;
        }

        for (const field of containers) {
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