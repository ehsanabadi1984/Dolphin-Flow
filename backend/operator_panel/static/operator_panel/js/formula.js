document.addEventListener("DOMContentLoaded", () => {
    const form = document.querySelector("form[data-instance-id]");
    if (!form) return;

    const instanceId = form.dataset.instanceId;
    const actionUrl = new URL(form.action);
    actionUrl.pathname = actionUrl.pathname.replace(/\/$/, "") + "/formula-definitions/";
    const endpoint = actionUrl.toString();

    const state = {
        fieldsById: new Map(),
        formulasById: new Map(),
        formulaResultsById: new Map(),
        suppressFormulaObserver: false,
        loading: false,
    };

    function toNumber(value) {
        if (value === null || value === undefined || value === "") return NaN;
        if (typeof value === "number") return value;
        const normalized = String(value)
            .trim()
            .replace(/,/g, "")
            .replace(/[۰-۹]/g, digit => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)));
        const number = Number(normalized);
        return Number.isFinite(number) ? number : NaN;
    }

    function formatNumber(value, decimalPlaces) {
        const places = Math.max(0, Math.min(Number(decimalPlaces) || 0, 6));
        if (!Number.isFinite(value)) return "";
        return value.toLocaleString("en-US", { minimumFractionDigits: places, maximumFractionDigits: places, useGrouping: false });
    }

    function getNormalFieldContainers() {
        return Array.from(form.querySelectorAll(".df-form-field[data-field-code]"));
    }

    function getNormalFormulaContainer(formula) {
        const containers = getNormalFieldContainers();

        for (const field of containers) {
            if (field.dataset.fieldCode === formula.code) return field;
        }

        const expectedIndex = Number(formula.dom_index);
        if (Number.isInteger(expectedIndex) && expectedIndex >= 0) {
            return containers[expectedIndex] || null;
        }

        return null;
    }

    function setNormalFormulaValue(formula, value) {
        const container = getNormalFormulaContainer(formula);
        console.debug("[Formula] target DOM", {
            code: formula.code,
            fieldId: formula.field_id,
            found: Boolean(container),
            container,
        });
        if (!container) return;
        let output = container.querySelector(".df-formula-value");
        if (!output) {
            output = document.createElement("div");
            output.className = "df-form-value df-formula-value";
            const fallback = container.querySelector(".df-form-value");
            if (fallback) fallback.replaceWith(output);
            else container.appendChild(output);
        }
        console.debug("[Formula] before DOM write", {
            code: formula.code,
            currentText: output.textContent,
            outputHTML: output.outerHTML,
        });
        output.textContent = formatNumber(value, formula.decimal_places);
        console.debug("[Formula] after DOM write", {
            code: formula.code,
            newText: output.textContent,
            outputHTML: output.outerHTML,
        });
        window.setTimeout(() => {
            console.debug("[Formula] after 0ms", {
                code: formula.code,
                connected: output.isConnected,
                currentText: output.textContent,
                outputHTML: output.outerHTML,
            });
        }, 0);
        window.setTimeout(() => {
            console.debug("[Formula] after 100ms", {
                code: formula.code,
                connected: output.isConnected,
                currentText: output.textContent,
                outputHTML: output.outerHTML,
            });
        }, 100);
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

    function isEditMode() {
        return form.dataset.editMode === "1";
    }

    function applyServerResults() {
        state.suppressFormulaObserver = true;
        for (const formula of state.formulasById.values()) {
            if (formula.calculation_only) continue;
            const result = state.formulaResultsById.get(Number(formula.field_id));
            if (!result) continue;
            if (formula.scope === "FORM") {
                console.debug("[Formula] formula result", {
                    fieldId: formula.field_id,
                    code: formula.code,
                    value: result.value,
                });
                setNormalFormulaValue(formula, toNumber(result.value));
                continue;
            }
            const group = form.querySelector(`[data-repeatable-group="${CSS.escape(formula.group_code)}"]`);
            if (!group) continue;
            const rows = group.querySelectorAll("[data-repeatable-item]:not([data-repeatable-template])");
            const values = Array.isArray(result.values) ? result.values : [];
            rows.forEach((row, index) => {
                const value = values[index] === undefined ? "" : values[index];
                if (group.classList.contains("df-table-group")) {
                    setRowFormulaValue(formula, row, toNumber(value));
                } else {
                    let output = row.querySelector(`.df-formula-value[data-formula-id="${formula.field_id}"]`);
                    if (!output) {
                        output = document.createElement("div");
                        output.className = "df-form-value df-formula-value";
                        output.dataset.formulaId = String(formula.field_id);
                        row.appendChild(output);
                    }
                    output.textContent = `${formula.label}: ${formatNumber(toNumber(value), formula.decimal_places)}`;
                }
            });
        }
        window.setTimeout(() => {
            state.suppressFormulaObserver = false;
        }, 0);
    }

    async function recalculate() {
        if (!isEditMode() || state.loading) return;
        state.loading = true;
        try {
            const formData = new FormData(form);
            console.debug("[Formula] POST payload", {
                entries: Array.from(formData.entries()),
            });
            const response = await fetch(`${endpoint}?instance_id=${encodeURIComponent(instanceId)}`, {
                method: "POST",
                body: formData,
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": getCsrfToken(),
                },
            });
            if (!response.ok) return;
            const payload = await response.json();
            console.debug("[Formula] POST response", payload);
            state.formulaResultsById.clear();
            for (const [fieldId, result] of Object.entries(payload.formula_results || {})) {
                state.formulaResultsById.set(Number(fieldId), result);
            }
            applyServerResults();
        } catch (error) {
            console.warn("Formula calculation could not be loaded:", error);
        } finally {
            state.loading = false;
        }
    }

    function getCsrfToken() {
        const input = form.querySelector('input[name="csrfmiddlewaretoken"]');
        if (input && input.value) return input.value;
        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    async function loadDefinitions() {
        if (state.loading) return;
        state.loading = true;
        try {
            const response = await fetch(`${endpoint}?instance_id=${encodeURIComponent(instanceId)}`, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (!response.ok) return;
            const payload = await response.json();
            state.fieldsById.clear();
            state.formulasById.clear();
            state.formulaResultsById.clear();
            for (const field of payload.fields || []) state.fieldsById.set(Number(field.id), field);
            for (const formula of payload.formulas || []) state.formulasById.set(Number(formula.field_id), formula);
            for (const [fieldId, result] of Object.entries(payload.formula_results || {})) {
                state.formulaResultsById.set(Number(fieldId), result);
            }
            applyServerResults();
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

    const observer = new MutationObserver(() => {
        if (!state.suppressFormulaObserver) scheduleRecalculate();
    });
    observer.observe(form, { childList: true, subtree: true });

    loadDefinitions();
});
