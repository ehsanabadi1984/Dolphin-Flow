import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const formulaAdminJs = readFileSync(
    resolve(here, "../formula_admin.js"),
    "utf8",
);

test("Formula Admin requests scoped fields for the selected group", () => {
    assert.match(
        formulaAdminJs,
        /new URLSearchParams\(\{section_id:sectionField\?\.value\|\|"",group_id:groupField\?\.value\|\|"",exclude_id:/,
    );
    assert.match(
        formulaAdminJs,
        /fetch\(\`\$\{optionsUrl\}\?\$\{params\.toString\(\)\}\`/,
    );
});

test("Formula Admin rebuilds the field selector from endpoint fields", () => {
    assert.match(
        formulaAdminJs,
        /fieldOptions=Array\.isArray\(payload\.fields\)\?payload\.fields:\[\]/,
    );
    assert.match(
        formulaAdminJs,
        /fieldOptions\.forEach\(field =>/,
    );
    assert.match(
        formulaAdminJs,
        /option\.value=field\.id/,
    );
});

test("Formula Admin preserves group scope metadata in field options", () => {
    assert.match(
        formulaAdminJs,
        /field\.is_group_field \? \`\$\{field\.section_label\} \/ \$\{field\.group_label \|\| field\.group_code\}\`/,
    );
});
