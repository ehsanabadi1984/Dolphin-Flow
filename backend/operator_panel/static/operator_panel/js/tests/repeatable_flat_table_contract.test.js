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
    assert.ok(
        rootTemplate.includes(
            'name="{{ cell.input_prefix }}{{ cell.field.code }}"',
        ),
    );
    assert.ok(
        rootTemplate.includes(
            'name="{{ group.group.code }}_TEMPLATE_{{ field_context.field.code }}"',
        ),
    );
    assert.doesNotMatch(
        rootTemplate,
        /name="{{ field_context\.field\.code }}"/,
    );
});

test("flat TABLE child templates keep the complete parent path", () => {
    assert.ok(
        nestedTemplate.includes(
            'name="PARENT_PREFIX{{ child_template.group.code }}_TEMPLATE_{{ field_context.field.code }}"',
        ),
    );

    assert.match(
        appJs,
        /\.replace\(\s*"PARENT_PREFIX",\s*`\$\{parentPath\}_`\s*\)/s,
    );

    assert.match(
        appJs,
        /\.replace\(\s*`_\$\{childGroupCode\}_TEMPLATE_`,\s*`_\$\{childGroupCode\}_\$\{childIndex\}_`\s*\)/s,
    );
});
test("flat TABLE root and child reindex keeps both root trees isolated", () => {
    const extractFunction = (source, functionName) => {
        const start = source.indexOf("function " + functionName + "(");
        assert.notEqual(start, -1, functionName + " must exist");
        let depth = 0;
        let opened = false;
        for (let index = source.indexOf("{", start); index < source.length; index += 1) {
            if (source[index] === "{") { depth += 1; opened = true; }
            else if (source[index] === "}") {
                depth -= 1;
                if (opened && depth === 0) return source.slice(start, index + 1);
            }
        }
        throw new Error("Could not extract " + functionName);
    };

    const makeField = (name) => ({
        name,
        getAttribute(attribute) { return attribute === "name" ? this.name : null; },
    });

    const makeRow = ({ id, group, parentId = "", path, fields }) => ({
        dataset: { rowId: id, repeatableRowGroup: group, parentRowId: parentId, rowPath: path, rootIndex: "" },
        fields,
        querySelectorAll(selector) { return selector === "input, textarea, select" ? this.fields : []; },
    });

    const rows = [];
    const container = {
        querySelector(selector) {
            const rowIdMatch = selector.match(/data-row-id="([^"]+)"/);
            if (!rowIdMatch) return null;
            return rows.find((row) => row.dataset.rowId === rowIdMatch[1]) || null;
        },
        querySelectorAll(selector) {
            if (!selector.includes("[data-repeatable-item]")) return [];
            const groupMatch = selector.match(/data-repeatable-row-group="([^"]+)"/);
            const parentMatch = selector.match(/data-parent-row-id="([^"]+)"/);
            return rows.filter((row) => {
                if (groupMatch && row.dataset.repeatableRowGroup !== groupMatch[1]) return false;
                if (parentMatch && row.dataset.parentRowId !== parentMatch[1]) return false;
                return true;
            });
        },
    };

    const root0Field = makeField("parts_0_name");
    const child0Field = makeField("parts_0_child_parts_0_address");
    const root1Field = makeField("parts_1_name");
    const child1Field = makeField("parts_1_child_parts_0_address");
    const root0 = makeRow({ id: "root-0", group: "parts", path: "parts_0", fields: [root0Field] });
    const child0 = makeRow({ id: "child-0", group: "child_parts", parentId: "root-0", path: "parts_0_child_parts_0", fields: [child0Field] });
    const root1 = makeRow({ id: "root-1", group: "parts", path: "parts_1", fields: [root1Field] });
    const child1 = makeRow({ id: "child-1", group: "child_parts", parentId: "root-1", path: "parts_1_child_parts_0", fields: [child1Field] });
    rows.push(root0, child0, root1, child1);

    const CSS = { escape: (value) => value };
    const escapeRegExp = extractFunction(appJs, "escapeRegExp");
    const rootReindex = extractFunction(appJs, "reindexFlatTableRootRows");
    const childReindex = extractFunction(appJs, "reindexFlatTableChildRows");
    const invoke = new Function("CSS", escapeRegExp + "\n" + rootReindex + "\n" + childReindex + "\nreturn { reindexFlatTableRootRows, reindexFlatTableChildRows };")(CSS);

    invoke.reindexFlatTableRootRows(container, "parts");
    assert.deepEqual(
        [root0Field.name, child0Field.name, root1Field.name, child1Field.name],
        ["parts_0_name", "parts_0_child_parts_0_address", "parts_1_name", "parts_1_child_parts_0_address"],
    );

    invoke.reindexFlatTableChildRows(container, "child_parts", "root-0", "parts_0");
    invoke.reindexFlatTableChildRows(container, "child_parts", "root-1", "parts_1");

    assert.deepEqual(
        [root0Field.name, child0Field.name, root1Field.name, child1Field.name],
        ["parts_0_name", "parts_0_child_parts_0_address", "parts_1_name", "parts_1_child_parts_0_address"],
    );
    assert.equal(new Set([root0Field.name, child0Field.name, root1Field.name, child1Field.name]).size, 4);
});
test("flat TABLE submit names stay unique after root and child mutations", () => {
    const extractFunction = (source, functionName) => {
        const start = source.indexOf("function " + functionName + "(");
        assert.notEqual(start, -1, functionName + " must exist");
        let depth = 0;
        let opened = false;
        for (let index = source.indexOf("{", start); index < source.length; index += 1) {
            if (source[index] === "{") { depth += 1; opened = true; }
            else if (source[index] === "}") {
                depth -= 1;
                if (opened && depth === 0) return source.slice(start, index + 1);
            }
        }
        throw new Error("Could not extract " + functionName);
    };

    const makeField = (name) => ({
        name,
        getAttribute(attribute) { return attribute === "name" ? this.name : null; },
    });

    const makeRow = ({ id, group, parentId = "", path, fields }) => ({
        dataset: { rowId: id, repeatableRowGroup: group, parentRowId: parentId, rowPath: path, rootIndex: "" },
        fields,
        querySelectorAll(selector) {
            return selector === "input, textarea, select" ? this.fields : [];
        },
    });

    const rows = [];
    const container = {
        querySelector(selector) {
            const rowIdMatch = selector.match(/data-row-id="([^"]+)"/);
            if (!rowIdMatch) return null;
            return rows.find((row) => row.dataset.rowId === rowIdMatch[1]) || null;
        },
        querySelectorAll(selector) {
            if (!selector.includes("[data-repeatable-item]")) return [];
            const groupMatch = selector.match(/data-repeatable-row-group="([^"]+)"/);
            const parentMatch = selector.match(/data-parent-row-id="([^"]+)"/);
            return rows.filter((row) => {
                if (groupMatch && row.dataset.repeatableRowGroup !== groupMatch[1]) return false;
                if (parentMatch && row.dataset.parentRowId !== parentMatch[1]) return false;
                return true;
            });
        },
    };

    const root0Field = makeField("parts_9_name");
    const child0Field = makeField("parts_9_child_parts_7_address");
    const root1Field = makeField("parts_3_name");
    const child1Field = makeField("parts_3_child_parts_4_address");
    const root0 = makeRow({ id: "root-0", group: "parts", path: "parts_9", fields: [root0Field] });
    const child0 = makeRow({ id: "child-0", group: "child_parts", parentId: "root-0", path: "parts_9_child_parts_7", fields: [child0Field] });
    const root1 = makeRow({ id: "root-1", group: "parts", path: "parts_3", fields: [root1Field] });
    const child1 = makeRow({ id: "child-1", group: "child_parts", parentId: "root-1", path: "parts_3_child_parts_4", fields: [child1Field] });
    rows.push(root0, child0, root1, child1);

    const CSS = { escape: (value) => value };
    const escapeRegExp = extractFunction(appJs, "escapeRegExp");
    const rootReindex = extractFunction(appJs, "reindexFlatTableRootRows");
    const childReindex = extractFunction(appJs, "reindexFlatTableChildRows");
    const invoke = new Function(
        "CSS",
        escapeRegExp + "\n" + rootReindex + "\n" + childReindex +
        "\nreturn { reindexFlatTableRootRows, reindexFlatTableChildRows };"
    )(CSS);

    invoke.reindexFlatTableRootRows(container, "parts");
    invoke.reindexFlatTableChildRows(container, "child_parts", "root-0", "parts_0");
    invoke.reindexFlatTableChildRows(container, "child_parts", "root-1", "parts_1");

    const submittedNames = rows.flatMap((row) =>
        row.fields.map((field) => field.getAttribute("name"))
    );

    assert.deepEqual(submittedNames, [
        "parts_0_name",
        "parts_0_child_parts_0_address",
        "parts_1_name",
        "parts_1_child_parts_0_address",
    ]);
    assert.equal(new Set(submittedNames).size, submittedNames.length);
    assert.ok(submittedNames.every((name) => !/^parts_[^_]+$/.test(name)));
    assert.deepEqual(
        submittedNames.filter((name) => name.endsWith("_name")),
        ["parts_0_name", "parts_1_name"],
    );
});

test("flat TABLE root reindex preserves child group segments", () => {
    assert.match(
        appJs,
        /const rootPattern\s*=\s*new RegExp\(\`\^\$\{escapeRegExp\(rootGroupCode\)\}_\\\\d\+_\`\);/s,
    );
    assert.match(
        appJs,
        /field\.name = name\.replace\(\s*rootPattern,\s*\`\$\{rootGroupCode\}_\$\{rootIndex\}_\`\s*\)/s,
    );
});
test("flat TABLE child add resolves the logical parent row path", () => {
    const extractFunction = (source, functionName) => {
        const start = source.indexOf("function " + functionName + "(");
        assert.notEqual(start, -1, functionName + " must exist");
        let depth = 0;
        let opened = false;
        for (let index = source.indexOf("{", start); index < source.length; index += 1) {
            if (source[index] === "{") { depth += 1; opened = true; }
            else if (source[index] === "}") {
                depth -= 1;
                if (opened && depth === 0) return source.slice(start, index + 1);
            }
        }
        throw new Error("Could not extract " + functionName);
    };

    const resolve = new Function(
        extractFunction(appJs, "getFlatTableChildParentPath") +
        "\nreturn getFlatTableChildParentPath;"
    )();

    const rows = [
        {
            dataset: {
                rowId: "child-0",
                rootIndex: "0",
                rowPath: "parts_0_child_parts_0",
            },
        },
    ];
    const table = {
        dataset: { repeatableGroup: "parts" },
        querySelector(selector) {
            const match = selector.match(/data-row-id="([^"]+)"/);
            return rows.find((row) => row.dataset.rowId === match?.[1]) || null;
        },

        querySelectorAll(selector) {
            if (selector !== "[data-repeatable-item]") return [];
            return rows;
        },
    };
    const visualChildRow = {
        dataset: {
            rootIndex: "0",
            rowPath: "parts_0_child_parts_0",
        },
    };

    assert.equal(
        resolve(table, visualChildRow, "root-0"),
        "parts_0",
    );

    assert.equal(
        resolve(table, visualChildRow, "child-0"),
        "parts_0_child_parts_0",
    );

    assert.equal(
        resolve(table, visualChildRow, ""),
        "parts_0",
    );
});

test("flat TABLE child row identity is scoped to its parent row path", () => {
    assert.match(
        appJs,
        /const childPrefix\s*=\s*\`\$\{parentPath\}_\$\{childGroupCode\}_\$\{childIndex\}_\`;/s,
    );
    assert.ok(
        appJs.includes("field.name = \`${childPrefix}__id\`;"),
    );
});