import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const formulaJs = readFileSync(resolve(here, "../formula.js"), "utf8");

test("live Formula endpoint is resolved beside the workflow instance URL", () => {
    assert.ok(formulaJs.includes("const actionUrl = new URL(form.action);"));
    assert.ok(formulaJs.includes('actionUrl.pathname = actionUrl.pathname.replace(/\\/$/, "") + "/formula-definitions/";'));
    assert.ok(!formulaJs.includes('new URL("formula-definitions/", form.action).toString()'));
});

test("live Formula recalculation listens to editable form changes", () => {
    assert.match(formulaJs, /form\.addEventListener\("input", scheduleRecalculate\);/);
    assert.match(formulaJs, /form\.addEventListener\("change", scheduleRecalculate\);/);
    assert.match(formulaJs, /method: "POST"/);
    assert.match(formulaJs, /const formData = new FormData\(form\);/);
    assert.match(formulaJs, /body: formData/);
});

test("live Formula response is applied to the visible Formula DOM", () => {
    assert.match(formulaJs, /applyServerResults\(\);/);
    assert.match(formulaJs, /output\.textContent = formatNumber\(value, formula\.decimal_places\);/);
});

test("normal Formula DOM lookup prefers the Formula field code over dom_index", () => {
    const lookup = formulaJs.slice(
        formulaJs.indexOf("function getNormalFormulaContainer"),
        formulaJs.indexOf("function setNormalFormulaValue"),
    );
    assert.match(
        lookup,
        /field\.dataset\.fieldCode === formula\.code\) return field;/,
    );
    assert.ok(
        lookup.indexOf("field.dataset.fieldCode === formula.code") <
        lookup.indexOf("const expectedIndex = Number(formula.dom_index);"),
    );
});
