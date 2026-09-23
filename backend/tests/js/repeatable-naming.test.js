import test from "node:test";
import assert from "node:assert/strict";

import "../../operator_panel/static/operator_panel/js/repeatable-naming.js";

const {
    reindexRepeatableFieldName,
    buildRepeatableGroupPrefix,
} = globalThis.DolphinFlowRepeatableNaming;

test("reindexes a root repeatable field", () => {
    assert.equal(
        reindexRepeatableFieldName(
            "customers_0_name",
            "customers_",
            1,
        ),
        "customers_1_name",
    );
});

test("reindexes a nested repeatable field without losing parent context", () => {
    assert.equal(
        reindexRepeatableFieldName(
            "customers_0_contacts_0_name",
            "customers_0_contacts_",
            1,
        ),
        "customers_0_contacts_1_name",
    );
});

test("reindexes the child independently for different parent rows", () => {
    assert.equal(
        reindexRepeatableFieldName(
            "customers_0_contacts_0_name",
            "customers_0_contacts_",
            1,
        ),
        "customers_0_contacts_1_name",
    );

    assert.equal(
        reindexRepeatableFieldName(
            "customers_1_contacts_0_name",
            "customers_1_contacts_",
            0,
        ),
        "customers_1_contacts_0_name",
    );
});

test("reindexes nested row identity name but preserves its value", () => {
    const name = reindexRepeatableFieldName(
        "customers_0_contacts_0__id",
        "customers_0_contacts_",
        1,
    );

    assert.equal(name, "customers_0_contacts_1__id");

    const value = "abc-123";
    assert.equal(value, "abc-123");
});

test("reindexes a deeper nested field while preserving the full ancestor path", () => {
    assert.equal(
        reindexRepeatableFieldName(
            "customers_0_contacts_0_addresses_0_city",
            "customers_0_contacts_",
            1,
        ),
        "customers_0_contacts_1_addresses_0_city",
    );
});

test("builds the full nested repeatable group prefix from parent context", () => {
    assert.equal(
        buildRepeatableGroupPrefix(
            [
                { groupCode: "customers", index: 0 },
            ],
            "contacts",
        ),
        "customers_0_contacts_",
    );

    assert.equal(
        buildRepeatableGroupPrefix(
            [
                { groupCode: "customers", index: 1 },
                { groupCode: "contacts", index: 0 },
            ],
            "addresses",
        ),
        "customers_1_contacts_0_addresses_",
    );
});
