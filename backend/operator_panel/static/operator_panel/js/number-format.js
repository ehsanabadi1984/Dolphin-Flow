(function () {
    "use strict";
    const digitMap = "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩";
    function normalizeDigits(value) {
        return String(value ?? "").replace(/[۰-۹٠-٩]/g, digit => String(digitMap.indexOf(digit) % 10));
    }
    function normalizeNumericText(value) {
        let normalized = normalizeDigits(value).trim().replace(/٫/g, ".").replace(/٬/g, ",");
        if (!normalized) return "";
        if (normalized.includes(",")) {
            const sign = /^[+-]/.test(normalized) ? normalized[0] : "";
            const unsigned = sign ? normalized.slice(1) : normalized;
            const integer = unsigned.split(".")[0];
            if (!/^\d{1,3}(,\d{3})+$/.test(integer)) return null;
            normalized = sign + unsigned.replace(/,/g, "");
        }
        return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(normalized) ? normalized : null;
    }
    function formatNumericText(value) {
        const normalized = normalizeNumericText(value);
        if (normalized === null) return String(value);
        if (normalized === "") return "";
        const match = normalized.match(/^([+-]?)(\d+)(\.\d*)?$/);
        if (!match) return normalized;
        return match[1] + match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (match[3] || "");
    }
    function enhanceInput(input) {
        if (!input || input.dataset.dfNumberReady === "1") return;
        input.dataset.dfNumberReady = "1";
        input.addEventListener("focus", () => {
            const normalized = normalizeNumericText(input.value);
            if (normalized !== null) input.value = normalized;
        });
        input.addEventListener("blur", () => { input.value = formatNumericText(input.value); });
        input.addEventListener("change", () => { input.value = formatNumericText(input.value); });
        input.value = formatNumericText(input.value);
    }
    function initialize(root) {
        const inputs = [];
        if (root?.matches?.("[data-df-number-input]")) inputs.push(root);
        if (root?.querySelectorAll) inputs.push(...root.querySelectorAll("[data-df-number-input]"));
        inputs.forEach(enhanceInput);
        const nodes = [];
        if (root?.matches?.("[data-df-number-display]")) nodes.push(root);
        if (root?.querySelectorAll) nodes.push(...root.querySelectorAll("[data-df-number-display]"));
        nodes.forEach(node => {
            if (node.dataset.dfNumberFormatted === "1") return;
            const formatted = formatNumericText(node.textContent);
            if (formatted !== null) {
                node.textContent = formatted;
                node.dataset.dfNumberFormatted = "1";
            }
        });
    }
    document.addEventListener("DOMContentLoaded", () => {
        initialize(document);
        const observer = new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
            if (node.nodeType === 1) initialize(node);
        })));
        observer.observe(document.body, { childList: true, subtree: true });
    });
    window.DolphinFlowNumberFormat = { normalize: normalizeNumericText, format: formatNumericText };
})();
