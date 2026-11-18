import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";

const scriptPath = new URL("../../operator_panel/static/operator_panel/js/number-format.js", import.meta.url);

test("formats inputs and dashboard values while preserving canonical edit values", async () => {
    const dom = new JSDOM('<input data-df-number-input value="۱۱۳۰۰۰۰۰"><input data-df-number-input value="-1250000.75"><div data-df-number-display>11300000</div>', { runScripts: "outside-only" });
    dom.window.eval(await readFile(scriptPath, "utf8"));
    dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
    const [integerInput, decimalInput] = dom.window.document.querySelectorAll("input");
    assert.equal(integerInput.value, "11٬300٬000");
    assert.equal(decimalInput.value, "-1٬250٬000.75");
    assert.equal(dom.window.document.querySelector("[data-df-number-display]").textContent, "11,300,000");
    integerInput.dispatchEvent(new dom.window.Event("focus"));
    assert.equal(integerInput.value, "11300000");
    integerInput.value = "۱۲,۵۰۰.۷۵";
    integerInput.dispatchEvent(new dom.window.Event("blur"));
    assert.equal(integerInput.value, "12٬500.75");
});

test("does not group values below one thousand and rejects malformed grouping", async () => {
    const dom = new JSDOM('<input data-df-number-input value="999.5"><input data-df-number-input value="12,50">', { runScripts: "outside-only" });
    dom.window.eval(await readFile(scriptPath, "utf8"));
    dom.window.document.dispatchEvent(new dom.window.Event("DOMContentLoaded"));
    const inputs = dom.window.document.querySelectorAll("input");
    assert.equal(inputs[0].value, "999.5");
    assert.equal(inputs[1].value, "12,50");
    assert.equal(dom.window.DolphinFlowNumberFormat.normalize("۱۱,۳۰۰,۰۰۰"), "11300000");
    assert.equal(dom.window.DolphinFlowNumberFormat.normalize("-1,250,000.75"), "-1250000.75");
});
