import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const formulaJs = readFileSync(
    resolve(here, "../formula.js"),
    "utf8",
);

test("Formula UI maps repeatable results by stable row_id, not visual row index", () => {
    assert.match(
        formulaJs,
        /const rowIds = Array\.isArray\(result\.row_ids\) \? result\.row_ids : \[\];/,
    );
    assert.match(
        formulaJs,
        /findRenderedRowById\(rowIds\[index\]\)/,
    );
    assert.doesNotMatch(
        formulaJs,
        /findRenderedRowByIndex/,
    );
});

test("Formula UI resolves Flat TABLE cells by group code and field code", () => {
    assert.match(
        formulaJs,
        /candidate\.dataset\.columnGroup === formula\.group_code/,
    );
    assert.match(
        formulaJs,
        /candidate\.dataset\.fieldCode === formula\.code/,
    );
    assert.match(
        formulaJs,
        /\[data-column-group\]\[data-field-code\]/,
    );
});

test("Formula UI keeps DEVICE Formula results scoped to the server-provided row identity", () => {
    assert.match(
        formulaJs,
        /const result = state\.formulaResultsById\.get\(Number\(formula\.field_id\)\);/,
    );
    assert.match(
        formulaJs,
        /if \(formula\.scope === "FORM"\)/,
    );
    assert.match(
        formulaJs,
        /const values = Array\.isArray\(result\.values\) \? result\.values : \[\];/,
    );
    assert.match(
        formulaJs,
        /const row = findRenderedRowById\(rowIds\[index\]\);/,
    );
    assert.match(
        formulaJs,
        /setRowFormulaValue\(formula, row, toNumber\(value\)\);/,
    );
});

test("Formula UI Flat TABLE row lookup excludes repeatable template rows", () => {
    assert.match(
        formulaJs,
        /\[data-repeatable-item\]:not\(\[data-repeatable-template\]\)/,
    );
    assert.match(
        formulaJs,
        /input\[data-repeatable-row-id\], input\[data-repeatable-root-row-id\]/,
    );
});
