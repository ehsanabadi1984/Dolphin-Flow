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
    root0.dataset.rootIndex = "0";
    const child0 = makeRow({ id: "child-0", group: "child_parts", parentId: "root-0", path: "parts_0_child_parts_0", fields: [child0Field] });
    child0.dataset.rootIndex = "0";
    const root1 = makeRow({ id: "root-1", group: "parts", path: "parts_1", fields: [root1Field] });
    root1.dataset.rootIndex = "1";
    const child1 = makeRow({ id: "child-1", group: "child_parts", parentId: "root-1", path: "parts_1_child_parts_0", fields: [child1Field] });
    child1.dataset.rootIndex = "1";
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
    root0.dataset.rootIndex = "9";
    const child0 = makeRow({ id: "child-0", group: "child_parts", parentId: "root-0", path: "parts_9_child_parts_7", fields: [child0Field] });
    child0.dataset.rootIndex = "9";
    const root1 = makeRow({ id: "root-1", group: "parts", path: "parts_3", fields: [root1Field] });
    root1.dataset.rootIndex = "3";
    const child1 = makeRow({ id: "child-1", group: "child_parts", parentId: "root-1", path: "parts_3_child_parts_4", fields: [child1Field] });
    child1.dataset.rootIndex = "3";
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
    assert.match(appJs, /const oldPrefix\s*=\s*\`\$\{rootGroupCode\}_\$\{oldIndex\}\`;/s);
    assert.match(appJs, /const newPrefix\s*=\s*\`\$\{rootGroupCode\}_\$\{newIndex\}\`;/s);
    assert.match(appJs, /const rootPattern\s*=\s*new RegExp\(/s);
    assert.match(appJs, /field\.name = name\.replace\(\s*rootPattern,\s*\`\$\{newPrefix\}_\`\s*\)/s);
    assert.match(appJs, /logicalRoots\.forEach\(\(\{ oldIndex, newIndex \}\) => \{/s);
    assert.match(appJs, /row\.dataset\.rootIndex = String\(newIndex\);/s);
});;
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
        appJs.includes("field.name = `${parentPath}_${childGroupCode}_${childIndex}__id`;"),
    );
});
test("flat TABLE child clone scopes field mutation to child template fields", () => {
    assert.match(appJs, /const isChildField\s*=\s*oldName\.startsWith\("PARENT_PREFIX"\)/s);
    assert.match(appJs, /const isChildRowId\s*=\s*isChildField\s*&&\s*field\.type === "hidden"\s*&&\s*oldName\.endsWith\("__id"\)/s);
    assert.match(appJs, /if \(!isChildField && !isChildRowId\) return/);
    assert.match(appJs, /field\.name = oldName\s*\.replace\(\s*"PARENT_PREFIX"/s);
});

test("flat TABLE browser-like add-child submit keeps root and child field names", () => {
    const rootName = "parts_create_0_address";
    const childTemplateName =
        "PARENT_PREFIXchild_parts_create_TEMPLATE_child_name";

    const rootField = {
        name: rootName,
        value: "Tehran",
        type: "text",
        tagName: "INPUT",
    };
    const childField = {
        name: childTemplateName,
        value: "",
        type: "text",
        tagName: "INPUT",
    };
    const childRowIdField = {
        name: "PARENT_PREFIXchild_parts_create_TEMPLATE__id",
        value: "",
        type: "hidden",
        tagName: "INPUT",
    };

    const childGroupCode = "child_parts_create";
    const parentPath = "parts_create_0";
    const childIndex = 0;
    const newRowId = "child-created-0";
    const childPrefix =
        `${parentPath}_${childGroupCode}_${childIndex}_`;

    const clonedFields = [childField, childRowIdField].map((field) => ({
        ...field,
    }));

    clonedFields.forEach((field) => {
        const oldName = field.name;
        const isChildField =
            oldName.startsWith("PARENT_PREFIX") &&
            oldName.includes(
                `${childGroupCode}_TEMPLATE_`
            );
        const isChildRowId =
            isChildField &&
            field.type === "hidden" &&
            oldName.endsWith("__id");

        if (!isChildField && !isChildRowId) {
            return;
        }

        if (isChildRowId) {
            field.name = `${parentPath}_${childGroupCode}_${childIndex}__id`;
            field.value = newRowId;
            return;
        }

        field.name = oldName
            .replace(
                "PARENT_PREFIX",
                `${parentPath}_`
            )
            .replace(
                `_${childGroupCode}_TEMPLATE_`,
                `_${childGroupCode}_${childIndex}_`
            );

        field.value = "";
    });

    clonedFields[0].value = "Child 1";

    const submittedFields = [rootField, ...clonedFields];

    const submittedNames = submittedFields.map((field) => field.name);
    const submittedValues = new Map(
        submittedFields.map((field) => [field.name, field.value]),
    );

    assert.deepEqual(
        submittedNames,
        [
            "parts_create_0_address",
            "parts_create_0_child_parts_create_0_child_name",
            "parts_create_0_child_parts_create_0__id",
        ],
    );
    assert.equal(
        submittedValues.get("parts_create_0_address"),
        "Tehran",
    );
    assert.equal(
        submittedValues.get(
            "parts_create_0_child_parts_create_0_child_name",
        ),
        "Child 1",
    );
    assert.equal(
        submittedValues.get(
            "parts_create_0_child_parts_create_0__id",
        ),
        newRowId,
    );
    assert.equal(new Set(submittedNames).size, submittedNames.length);

    /*
     * The root field must not be touched by the child-clone operation.
     * This is the exact regression we are protecting against.
     */
    assert.equal(rootField.name, rootName);
    assert.equal(rootField.value, "Tehran");
});

test("flat TABLE add-child lifecycle preserves root value through reindex and submit", () => {
    const extractFunction = (source, functionName) => {
        const start = source.indexOf("function " + functionName + "(");
        assert.notEqual(start, -1, functionName + " must exist");
        let depth = 0;
        let opened = false;
        for (let index = source.indexOf("{", start); index < source.length; index += 1) {
            if (source[index] === "{") {
                depth += 1;
                opened = true;
            } else if (source[index] === "}") {
                depth -= 1;
                if (opened && depth === 0) {
                    return source.slice(start, index + 1);
                }
            }
        }
        throw new Error("Could not extract " + functionName);
    };

    const makeField = (name, value = "", type = "text") => ({
        name,
        value,
        type,
        tagName: "INPUT",
        getAttribute(attribute) {
            return attribute === "name" ? this.name : null;
        },
    });

    const makeRow = ({
        id,
        group,
        parentId = "",
        path,
        fields,
    }) => ({
        dataset: {
            rowId: id,
            repeatableRowGroup: group,
            parentRowId: parentId,
            rowPath: path,
            rootIndex: "0",
        },
        fields,
        querySelectorAll(selector) {
            return selector === "input, textarea, select"
                ? this.fields
                : [];
        },
    });

    const rootGroupCode = "parts_create";
    const childGroupCode = "child_parts_create";
    const parentPath = "parts_create_0";
    const rootRowId = "root-create-0";
    const childRowId = "child-created-0";

    const rootField = makeField(
        "parts_create_0_address",
        "Tehran",
    );
    const rootRow = makeRow({
        id: rootRowId,
        group: rootGroupCode,
        path: parentPath,
        fields: [rootField],
    });

    const childTemplateFields = [
        makeField(
            "PARENT_PREFIXchild_parts_create_TEMPLATE_child_name",
            "",
        ),
        makeField(
            "PARENT_PREFIXchild_parts_create_TEMPLATE__id",
            "",
            "hidden",
        ),
    ];

    /*
     * Simulate the actual browser Add Child operation.
     * The root row remains in the same container; only the child
     * template is cloned and its child-owned fields are rewritten.
     */
    const childIndex = 0;
    const clonedChildFields = childTemplateFields.map((field) => ({
        ...field,
    }));

    clonedChildFields.forEach((field) => {
        const oldName = field.name;
        const isChildField =
            oldName.startsWith("PARENT_PREFIX") &&
            oldName.includes(
                childGroupCode + "_TEMPLATE_",
            );
        const isChildRowId =
            field.type === "hidden" &&
            oldName.endsWith("__id");

        if (!isChildField && !isChildRowId) {
            return;
        }

        if (isChildRowId) {
            field.name =
                parentPath +
                "_" +
                childGroupCode +
                "_" +
                childIndex +
                "__id";
            field.value = childRowId;
            return;
        }

        field.name = oldName
            .replace(
                "PARENT_PREFIX",
                parentPath + "_",
            )
            .replace(
                "_" + childGroupCode + "_TEMPLATE_",
                "_" + childGroupCode + "_" + childIndex + "_",
            );
        field.value = "Child 1";
    });

    const childRow = makeRow({
        id: childRowId,
        group: childGroupCode,
        parentId: rootRowId,
        path: parentPath + "_" + childGroupCode + "_0",
        fields: clonedChildFields,
    });

    const rows = [rootRow, childRow];

    const container = {
        querySelector(selector) {
            const rowIdMatch =
                selector.match(/data-row-id="([^"]+)"/);
            if (!rowIdMatch) {
                return null;
            }
            return rows.find(
                (row) => row.dataset.rowId === rowIdMatch[1],
            ) || null;
        },
        querySelectorAll(selector) {
            if (!selector.includes("[data-repeatable-item]")) {
                return [];
            }

            const groupMatch =
                selector.match(
                    /data-repeatable-row-group="([^"]+)"/,
                );
            const parentMatch =
                selector.match(
                    /data-parent-row-id="([^"]+)"/,
                );

            return rows.filter((row) => {
                if (
                    groupMatch &&
                    row.dataset.repeatableRowGroup !== groupMatch[1]
                ) {
                    return false;
                }
                if (
                    parentMatch &&
                    row.dataset.parentRowId !== parentMatch[1]
                ) {
                    return false;
                }
                return true;
            });
        },
    };

    const CSS = {
        escape: (value) => value,
    };
    const invoke = new Function(
        "CSS",
        extractFunction(appJs, "escapeRegExp") +
            "\n" +
            extractFunction(appJs, "reindexFlatTableRootRows") +
            "\n" +
            extractFunction(appJs, "reindexFlatTableChildRows") +
            "\nreturn { reindexFlatTableRootRows, reindexFlatTableChildRows };",
    )(CSS);

    /*
     * Simulate the lifecycle after Add Child:
     * root reindex -> child reindex -> native form submission.
     */
    invoke.reindexFlatTableRootRows(
        container,
        rootGroupCode,
    );
    invoke.reindexFlatTableChildRows(
        container,
        childGroupCode,
        rootRowId,
        parentPath,
    );

    const submittedFields = rows.flatMap(
        (row) => row.fields,
    );

    const submittedNames = submittedFields.map(
        (field) => field.name,
    );
    const submittedValues = new Map(
        submittedFields.map(
            (field) => [field.name, field.value],
        ),
    );

    assert.equal(
        rootField.name,
        "parts_create_0_address",
    );
    assert.equal(
        rootField.value,
        "Tehran",
    );
    assert.equal(
        submittedValues.get(
            "parts_create_0_address",
        ),
        "Tehran",
    );
    assert.equal(
        submittedValues.get(
            "parts_create_0_child_parts_create_0_child_name",
        ),
        "Child 1",
    );
    assert.equal(
        submittedValues.get(
            "parts_create_0_child_parts_create_0__id",
        ),
        childRowId,
    );
    assert.deepEqual(
        submittedNames,
        [
            "parts_create_0_address",
            "parts_create_0_child_parts_create_0_child_name",
            "parts_create_0_child_parts_create_0__id",
        ],
    );
    assert.equal(
        new Set(submittedNames).size,
        submittedNames.length,
    );
});


test("flat TABLE four independent root trees keep unique root and child names after adding a child", () => {
    const extractFunction = (source, functionName) => {
        const start = source.indexOf("function " + functionName + "(");
        assert.notEqual(start, -1, functionName + " must exist");
        let depth = 0;
        let opened = false;

        for (
            let index = source.indexOf("{", start);
            index < source.length;
            index += 1
        ) {
            if (source[index] === "{") {
                depth += 1;
                opened = true;
            } else if (source[index] === "}") {
                depth -= 1;
                if (opened && depth === 0) {
                    return source.slice(start, index + 1);
                }
            }
        }

        throw new Error("Could not extract " + functionName);
    };

    const makeField = (name, value = "") => ({
        name,
        value,
        type: "text",
        tagName: "INPUT",
        getAttribute(attribute) {
            return attribute === "name" ? this.name : null;
        },
    });

    const makeRow = ({
        id,
        group,
        parentId,
        path,
        fields,
    }) => ({
        dataset: {
            rowId: id,
            repeatableRowGroup: group,
            parentRowId: parentId,
            rowPath: path,
            rootIndex: path.split("_")[1],
        },
        fields,
        querySelectorAll(selector) {
            return selector === "input, textarea, select"
                ? this.fields
                : [];
        },
    });

    const rootGroupCode = "parts";
    const childGroupCode = "child_parts";

    /*
     * A populated root is rendered as child visual rows in a flat TABLE.
     * Each of the four roots therefore owns its own child row, and the
     * ancestor fields are rendered only on that root's first child row.
     */
    const roots = [
        ["root-0", "child-0", "علی", "تهران"],
        ["root-1", "child-1", "سعید", "تهران نیست"],
        ["root-2", "child-2", "رضا", "اصفهان"],
        ["root-3", "child-3", "مریم", "شیراز"],
    ];

    const rows = roots.flatMap(
        ([rootId, childId, name, address], rootIndex) => [
            makeRow({
                id: childId,
                group: childGroupCode,
                parentId: rootId,
                path: `${rootGroupCode}_${rootIndex}_${childGroupCode}_0`,
                fields: [
                    makeField(
                        `${rootGroupCode}_${rootIndex}_OwnerName`,
                        name,
                    ),
                    makeField(
                        `${rootGroupCode}_${rootIndex}_OwnerAddress`,
                        address,
                    ),
                    makeField(
                        `${rootGroupCode}_${rootIndex}_${childGroupCode}_0_Phone`,
                        `09${rootIndex}0000000`,
                    ),
                ],
            }),
        ],
    );

    /*
     * Add a second child to root 0. The new child has no ancestor fields;
     * those remain owned by root 0's first visual child row.
     */
    rows.push(
        makeRow({
            id: "child-0-new",
            group: childGroupCode,
            parentId: "root-0",
            path: `${rootGroupCode}_0_${childGroupCode}_1`,
            fields: [
                makeField(
                    `${rootGroupCode}_0_${childGroupCode}_1_Phone`,
                    "09120000000",
                ),
            ],
        }),
    );

    const container = {
        querySelector(selector) {
            const rowIdMatch = selector.match(
                /data-row-id="([^"]+)"/,
            );
            if (!rowIdMatch) {
                return null;
            }

            return rows.find(
                (row) => row.dataset.rowId === rowIdMatch[1],
            ) || null;
        },

        querySelectorAll(selector) {
            if (!selector.includes("[data-repeatable-item]")) {
                return [];
            }

            const groupMatch = selector.match(
                /data-repeatable-row-group="([^"]+)"/,
            );
            const parentMatch = selector.match(
                /data-parent-row-id="([^"]+)"/,
            );

            return rows.filter((row) => {
                if (
                    groupMatch &&
                    row.dataset.repeatableRowGroup !== groupMatch[1]
                ) {
                    return false;
                }

                if (
                    parentMatch &&
                    row.dataset.parentRowId !== parentMatch[1]
                ) {
                    return false;
                }

                return true;
            });
        },
    };

    const CSS = {
        escape: (value) => value,
    };

    const invoke = new Function(
        "CSS",
        extractFunction(appJs, "escapeRegExp") +
            "\n" +
            extractFunction(appJs, "reindexFlatTableRootRows") +
            "\n" +
            extractFunction(appJs, "reindexFlatTableChildRows") +
            "\nreturn { reindexFlatTableRootRows, reindexFlatTableChildRows };",
    )(CSS);

    /*
     * Re-run the same reindex lifecycle used after flat-table mutations.
     * Root rows are represented by child visual rows here, so the child
     * trees must remain isolated by their logical parent path.
     */
    invoke.reindexFlatTableRootRows(
        container,
        rootGroupCode,
    );

    for (let rootIndex = 0; rootIndex < roots.length; rootIndex += 1) {
        invoke.reindexFlatTableChildRows(
            container,
            childGroupCode,
            `root-${rootIndex}`,
            `${rootGroupCode}_${rootIndex}`,
        );
    }

    const submittedFields = rows.flatMap((row) => row.fields);
    const submittedNames = submittedFields.map(
        (field) => field.getAttribute("name"),
    );

    /*
     * Every root must have exactly one OwnerName and OwnerAddress key.
     * If two roots collapse onto the same key, Django QueryDict would
     * receive values such as ['علی', 'سعید'] instead of independent rows.
     */
    assert.deepEqual(
        submittedNames.filter((name) => name.endsWith("_OwnerName")),
        [
            "parts_0_OwnerName",
            "parts_1_OwnerName",
            "parts_2_OwnerName",
            "parts_3_OwnerName",
        ],
    );

    assert.deepEqual(
        submittedNames.filter((name) => name.endsWith("_OwnerAddress")),
        [
            "parts_0_OwnerAddress",
            "parts_1_OwnerAddress",
            "parts_2_OwnerAddress",
            "parts_3_OwnerAddress",
        ],
    );

    assert.deepEqual(
        submittedNames.filter((name) => name.includes("_child_parts_")),
        [
            "parts_0_child_parts_0_Phone",
            "parts_1_child_parts_0_Phone",
            "parts_2_child_parts_0_Phone",
            "parts_3_child_parts_0_Phone",
            "parts_0_child_parts_1_Phone",
        ],
    );

    assert.equal(
        new Set(submittedNames).size,
        submittedNames.length,
        "flat TABLE submit names must remain globally unique",
    );
});

test("flat TABLE deleting the first child preserves the logical root", () => {
    assert.match(
        appJs,
        /function preserveFlatTableRootOnChildDelete\(container, childRow, rootGroupCode\)/,
    );
    assert.match(
        appJs,
        /const rootRowId = childRow\.dataset\.parentRowId;/,
    );
    assert.match(
        appJs,
        /if \(siblingChildren\.length\) \{[\s\S]*?rootCells\.forEach\(\(sourceCell, index\) =>/,
    );
    assert.match(
        appJs,
        /childRow\.dataset\.repeatableRowGroup = rootGroupCode;[\s\S]*?childRow\.dataset\.rowId = rootRowId;/s,
    );
    assert.match(
        appJs,
        /rootIdInput\.name =\s*\`\$\{rootGroupCode\}_\$\{rootIndex\}__id\`;/s,
    );
    assert.match(
        appJs,
        /preserveFlatTableRootOnChildDelete\(\s*container,\s*flatRow,\s*rootGroupCode\s*\)/s,
    );
});

test("flat TABLE root reindex handles roots represented only by child rows", () => {
    const extractFunction = (source, functionName) => {
        const start = source.indexOf("function " + functionName + "(");
        assert.notEqual(start, -1, functionName + " must exist");
        let depth = 0;
        let opened = false;
        for (let index = source.indexOf("{", start); index < source.length; index += 1) {
            if (source[index] === "{") {
                depth += 1;
                opened = true;
            } else if (source[index] === "}") {
                depth -= 1;
                if (opened && depth === 0) return source.slice(start, index + 1);
            }
        }
        throw new Error("Could not extract " + functionName);
    };

    const makeField = (name) => ({
        name,
        getAttribute(attribute) {
            return attribute === "name" ? this.name : null;
        },
    });

    const makeRow = (id, rootIndex, path, fields) => ({
        dataset: {
            rowId: id,
            repeatableRowGroup: "child_parts",
            rootIndex: String(rootIndex),
            rowPath: path,
        },
        fields,
        querySelectorAll(selector) {
            return selector === "input, textarea, select" ? this.fields : [];
        },
    });

    const rows = [
        makeRow("child-a", 0, "parts_0_child_parts_0", [
            makeField("parts_0_OwnerName"),
            makeField("parts_0_OwnerAddress"),
            makeField("parts_0_child_parts_0_Phone"),
        ]),
        makeRow("child-b", 1, "parts_1_child_parts_0", [
            makeField("parts_1_OwnerName"),
            makeField("parts_1_OwnerAddress"),
            makeField("parts_1_child_parts_0_Phone"),
        ]),
    ];

    const container = {
        querySelectorAll(selector) {
            return selector === "[data-repeatable-item]" ? rows : [];
        },
    };

    const CSS = { escape: (value) => value };
    const invoke = new Function(
        "CSS",
        extractFunction(appJs, "escapeRegExp") +
            "\n" +
            extractFunction(appJs, "reindexFlatTableRootRows") +
            "\nreturn { reindexFlatTableRootRows };",
    )(CSS);

    invoke.reindexFlatTableRootRows(container, "parts");

    assert.deepEqual(
        rows.flatMap((row) => row.fields.map((field) => field.name)),
        [
            "parts_0_OwnerName",
            "parts_0_OwnerAddress",
            "parts_0_child_parts_0_Phone",
            "parts_1_OwnerName",
            "parts_1_OwnerAddress",
            "parts_1_child_parts_0_Phone",
        ],
    );
    assert.deepEqual(
        rows.map((row) => row.dataset.rowPath),
        [
            "parts_0_child_parts_0",
            "parts_1_child_parts_0",
        ],
    );
    assert.equal(
        new Set(rows.flatMap((row) => row.fields.map((field) => field.name))).size,
        6,
    );
});
