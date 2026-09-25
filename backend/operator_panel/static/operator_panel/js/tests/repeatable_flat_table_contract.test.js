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
        /const flatRow = repeatableDeleteBtn\.closest\(\s*"\.df-repeatable-flat-row, \[data-repeatable-item\]"\s*\);/,
    );
    assert.match(
        appJs,
        /const flatTable = flatRow\?\.closest\("\.df-table-group"\);/,
    );
    assert.match(
        appJs,
        /if \(rowGroupCode === rootGroupCode\)/,
    );
});


test("flat TABLE child clones become live rows for delete handling", () => {
    assert.match(
        appJs,
        /newItem\.removeAttribute\("data-repeatable-child-template"\);\s*newItem\.setAttribute\("data-repeatable-item", ""\);/s,
    );
    assert.match(
        appJs,
        /newItem\.classList\.remove\("df-repeatable-flat-template"\);\s*newItem\.classList\.add\("df-repeatable-flat-row"\);/s,
    );
});


test("flat TABLE root delete uses serialized group permission contract", () => {
    assert.match(
        rootTemplate,
        /{% if edit_mode and not dynamic_form\.is_submitted and group\.can_delete %}/,
    );
    assert.doesNotMatch(
        rootTemplate,
        /group\.permissions\.can_delete/,
    );
});

test("flat TABLE root field names remain root-scoped", () => {
    assert.match(
        rootTemplate,
        /name="{{ cell\\.input_prefix }}{{ cell\\.field\\.code }}"/,
    );
    assert.match(
        rootTemplate,
        /name="{{ group\\.group\\.code }}_TEMPLATE_{{ field_context\\.field\\.code }}"/,
    );
    assert.doesNotMatch(
        rootTemplate,
        /name="{{ field_context\\.field\\.code }}"/,
    );
});

test("flat TABLE child templates keep the complete parent path", () => {
    assert.match(
        nestedTemplate,
        /name="PARENT_PREFIX{{ child_template\\.group\\.code }}_TEMPLATE_{{ field_context\\.field\\.code }}"/,
    );
    assert.match(
        appJs,
        /\\.replace\\(\\s*"PARENT_PREFIX",\\s*\\x60\\$\\{parentRow\\.dataset\\.rowPath\\}_\\x60\\s*\\)/s,
    );
    assert.match(
        appJs,
        /\\.replace\\(\\s*\\x60_\\$\\{childGroupCode\\}_TEMPLATE_\\x60,\\s*\\x60_\\$\\{childGroupCode\\}_\\$\\{childIndex\\}_\\x60\\s*\\)/s,
    );
});

test("flat TABLE root reindex preserves child group segments", () => {
    assert.match(
        appJs,
        /const rootPattern =\\s*new RegExp\\(\\x60\\^\\$\\{escapeRegExp\\(rootGroupCode\\)\\}_\\\\\\\\d\\+_\\x60\\)/s,
    );
    assert.match(
        appJs,
        /field\\.name = name\\.replace\\(\\s*rootPattern,\\s*\\x60\\$\\{rootGroupCode\\}_\\$\\{rootIndex\\}_\\x60\\s*\\)/s,
    );
});

test("flat TABLE child row identity is scoped to its parent row path", () => {
    assert.match(
        appJs,
        /const childPrefix =\\s*\\x60\\$\\{parentRow\\.dataset\\.rowPath\\}_\\$\\{childGroupCode\\}_\\$\\{childIndex\\}_\\x60;/s,
    );
    assert.match(
        appJs,
        /field\\.name = `\\$\\{childPrefix\\}__id`;/,
    );
});
