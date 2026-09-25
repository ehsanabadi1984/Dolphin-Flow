import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const operatorPanel = resolve(here, "../..");
const templates = resolve(operatorPanel, "../../templates/operator_panel");

const appJs = readFileSync(
    resolve(operatorPanel, "js/app.js"),
    "utf8",
);
const rootTemplate = readFileSync(
    resolve(templates, "_repeatable_flat_table.html"),
    "utf8",
);
const nestedTemplate = readFileSync(
    resolve(templates, "_repeatable_flat_table_templates.html"),
    "utf8",
);

test("flat TABLE root clone keeps recursive child-add contract", () => {
    assert.match(
        rootTemplate,
        /group\.flat_table\.child_templates/,
    );
    assert.ok(rootTemplate.includes("df-repeatable-child-add"));
    assert.match(
        rootTemplate,
        /data-group-code="{{ child_template\.group\.code }}"/,
    );

    assert.match(
        nestedTemplate,
        /child_template\.child_groups/,
    );
    assert.ok(nestedTemplate.includes("df-repeatable-child-add"));
    assert.match(
        nestedTemplate,
        /data-group-code="{{ nested_template\.group\.code }}"/,
    );
});

test("flat TABLE row cloning propagates the new parent row id to child actions", () => {
    assert.match(
        appJs,
        /newItem\.querySelectorAll\(\s*"\.df-repeatable-child-add"\s*\)\.forEach\(\(button\) => \{\s*button\.dataset\.parentRowId = newRowId;/s,
    );
});

test("flat TABLE root and child templates expose delete actions", () => {
    assert.ok(rootTemplate.includes("df-repeatable-delete"));
    assert.match(
        rootTemplate,
        /data-delete-label="{{ group\.group\.label }}"/,
    );
    assert.ok(nestedTemplate.includes("df-repeatable-delete"));
    assert.match(
        nestedTemplate,
        /data-delete-label="{{ child_template\.group\.label }}"/,
    );
});

test("flat TABLE delete handler covers root and child rows", () => {
    assert.match(
        appJs,
        /const flatTable = repeatableDeleteBtn\.closest\("\.df-table-group"\);/,
    );
    assert.match(
        appJs,
        /if \(rowGroupCode === rootGroupCode\)/,
    );
});
