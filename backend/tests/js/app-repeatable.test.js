import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import { JSDOM } from "jsdom";

const appPath = new URL(
    "../../operator_panel/static/operator_panel/js/app.js",
    import.meta.url
);

test("adds a nested child row under the second parent with isolated names", async () => {
    const dom = new JSDOM(
        `
        <button id="df-notification-toggle" type="button" aria-expanded="false"></button>
        <div id="df-notification-menu" aria-hidden="true">
            <div id="df-notification-list"></div>
            <span id="df-notification-badge"></span>
            <span id="df-notification-menu-count"></span>
        </div>

        <form data-instance-id="1" data-edit-mode="1">
            <section class="df-repeatable-group" data-repeatable-group="customers">
                <div class="df-repeatable-items">
                    <div class="df-repeatable-item" data-repeatable-item>
                        <input name="customers_0_name" value="Parent 1">
                        <section class="df-repeatable-group df-repeatable-child-group" data-repeatable-group="contacts">
                            <div class="df-repeatable-items">
                                <div class="df-repeatable-item" data-repeatable-item>
                                    <input name="customers_0_contacts_0_name" value="First child">
                                    <input type="hidden" name="customers_0_contacts_0__id" value="child-1">
                                </div>
                            </div>
                            <button type="button" class="df-repeatable-add" data-group-code="contacts">
                                + افزودن
                            </button>
                        </section>
                    </div>

                    <div class="df-repeatable-item" data-repeatable-item>
                        <input name="customers_1_name" value="Parent 2">
                        <section class="df-repeatable-group df-repeatable-child-group" data-repeatable-group="contacts">
                            <div class="df-repeatable-items">
                                <div class="df-repeatable-item" data-repeatable-item>
                                    <input name="customers_1_contacts_0_name" value="Second parent child">
                                    <input type="hidden" name="customers_1_contacts_0__id" value="child-2">
                                </div>
                            </div>
                            <button type="button" class="df-repeatable-add" data-group-code="contacts">
                                + افزودن
                            </button>
                        </section>
                    </div>
                </div>
            </section>
        </form>
        `,
        {
            url: "http://localhost/workflow/1/",
            runScripts: "outside-only",
        }
    );

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.CSS = dom.window.CSS || {};
    if (typeof globalThis.CSS.escape !== "function") {
        globalThis.CSS.escape = (value) =>
            String(value).replace(/[^a-zA-Z0-9_-]/g, (character) =>
                "\\" + character.codePointAt(0).toString(16) + " "
            );
    }
    dom.window.CSS = globalThis.CSS;
    globalThis.confirm = () => true;
    dom.window.confirm = () => true;
    dom.window.confirm = () => true;
    globalThis.setTimeout = () => 0;
    globalThis.clearTimeout = () => {};

    class WebSocketStub {
        static OPEN = 1;
        static CONNECTING = 0;

        constructor() {
            this.readyState = WebSocketStub.OPEN;
        }

        addEventListener() {}
    }

    globalThis.WebSocket = WebSocketStub;
    dom.window.WebSocket = WebSocketStub;

    const namingPath = new URL(
        "../../operator_panel/static/operator_panel/js/repeatable-naming.js",
        import.meta.url
    );
    const namingSource = await readFile(namingPath, "utf8");
    dom.window.eval(namingSource);
    globalThis.reindexRepeatableFieldName =
        dom.window.DolphinFlowRepeatableNaming.reindexRepeatableFieldName;
    globalThis.buildRepeatableGroupPrefix =
        dom.window.DolphinFlowRepeatableNaming.buildRepeatableGroupPrefix;
    await import(`${appPath.href}?repeatable-dom-test`);

    document.dispatchEvent(
        new dom.window.Event("DOMContentLoaded", { bubbles: true })
    );

    const parentRows = document.querySelectorAll(
        ".df-repeatable-group[data-repeatable-group=\"customers\"] > .df-repeatable-items > [data-repeatable-item]"
    );

    const secondParent = parentRows[1];
    const childGroup = secondParent.querySelector(
        ".df-repeatable-group[data-repeatable-group=\"contacts\"]"
    );
    const addButton = childGroup.querySelector(".df-repeatable-add");

    addButton.dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true })
    );

    const firstParentChildNames = Array.from(
        parentRows[0].querySelectorAll(
            ".df-repeatable-child-group input[name]"
        )
    ).map((input) => input.name);

    const secondParentChildNames = Array.from(
        parentRows[1].querySelectorAll(
            ".df-repeatable-child-group input[name]"
        )
    ).map((input) => input.name);

    assert.deepEqual(firstParentChildNames, [
        "customers_0_contacts_0_name",
        "customers_0_contacts_0__id",
    ]);

    assert.deepEqual(secondParentChildNames, [
        "customers_1_contacts_0_name",
        "customers_1_contacts_0__id",
        "customers_1_contacts_1_name",
        "customers_1_contacts_1__id",
    ]);

    assert.equal(
        parentRows[1].querySelector(
            'input[name="customers_1_contacts_1_name"]'
        ).value,
        ""
    );

    assert.notEqual(
        parentRows[1].querySelector(
            'input[name="customers_1_contacts_1__id"]'
        ).value,
        "child-2"
    );

    dom.window.close();
});


test("deletes a nested child row under the second parent without affecting the first parent", async () => {
    const dom = new JSDOM(
        `
        <button id="df-notification-toggle" type="button" aria-expanded="false"></button>
        <div id="df-notification-menu" aria-hidden="true">
            <div id="df-notification-list"></div>
            <span id="df-notification-badge"></span>
            <span id="df-notification-menu-count"></span>
        </div>

        <form data-instance-id="1" data-edit-mode="1">
            <section class="df-repeatable-group" data-repeatable-group="customers">
                <div class="df-repeatable-items">
                    <div class="df-repeatable-item" data-repeatable-item>
                        <input name="customers_0_name" value="Parent 1">
                        <section class="df-repeatable-group df-repeatable-child-group" data-repeatable-group="contacts">
                            <div class="df-repeatable-items">
                                <div class="df-repeatable-item" data-repeatable-item>
                                    <input name="customers_0_contacts_0_name" value="First parent child">
                                    <input type="hidden" name="customers_0_contacts_0__id" value="child-1">
                                    <button type="button" class="df-repeatable-delete">حذف</button>
                                </div>
                            </div>
                        </section>
                    </div>

                    <div class="df-repeatable-item" data-repeatable-item>
                        <input name="customers_1_name" value="Parent 2">
                        <section class="df-repeatable-group df-repeatable-child-group" data-repeatable-group="contacts">
                            <div class="df-repeatable-items">
                                <div class="df-repeatable-item" data-repeatable-item>
                                    <input name="customers_1_contacts_0_name" value="Keep child">
                                    <input type="hidden" name="customers_1_contacts_0__id" value="child-2">
                                    <button type="button" class="df-repeatable-delete">حذف</button>
                                </div>
                                <div class="df-repeatable-item" data-repeatable-item>
                                    <input name="customers_1_contacts_1_name" value="Delete child">
                                    <input type="hidden" name="customers_1_contacts_1__id" value="child-3">
                                    <button type="button" class="df-repeatable-delete">حذف</button>
                                </div>
                            </div>
                        </section>
                    </div>
                </div>
            </section>
        </form>
        `,
        {
            url: "http://localhost/workflow/1/",
            runScripts: "outside-only",
        }
    );

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.CSS = dom.window.CSS || {};
    if (typeof globalThis.CSS.escape !== "function") {
        globalThis.CSS.escape = (value) =>
            String(value).replace(/[^a-zA-Z0-9_-]/g, (character) =>
                "\\" + character.codePointAt(0).toString(16) + " "
            );
    }
    globalThis.confirm = () => true;
    dom.window.confirm = () => true;
    globalThis.setTimeout = () => 0;
    globalThis.clearTimeout = () => {};

    class WebSocketStub {
        static OPEN = 1;
        static CONNECTING = 0;

        constructor() {
            this.readyState = WebSocketStub.OPEN;
        }

        addEventListener() {}
    }

    globalThis.WebSocket = WebSocketStub;
    dom.window.WebSocket = WebSocketStub;

    const namingPath = new URL(
        "../../operator_panel/static/operator_panel/js/repeatable-naming.js",
        import.meta.url
    );
    const namingSource = await readFile(namingPath, "utf8");
    dom.window.eval(namingSource);
    globalThis.reindexRepeatableFieldName =
        dom.window.DolphinFlowRepeatableNaming.reindexRepeatableFieldName;
    globalThis.buildRepeatableGroupPrefix =
        dom.window.DolphinFlowRepeatableNaming.buildRepeatableGroupPrefix;
    await import(`${appPath.href}?repeatable-delete-test`);

    document.dispatchEvent(
        new dom.window.Event("DOMContentLoaded", { bubbles: true })
    );

    const parentRows = document.querySelectorAll(
        ".df-repeatable-group[data-repeatable-group=\"customers\"] > .df-repeatable-items > [data-repeatable-item]"
    );
    const secondParent = parentRows[1];
    const childRows = secondParent.querySelectorAll(
        ".df-repeatable-child-group .df-repeatable-items > [data-repeatable-item]"
    );

    childRows[1].querySelector(".df-repeatable-delete").dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true })
    );

    const firstParentChildNames = Array.from(
        parentRows[0].querySelectorAll(
            ".df-repeatable-child-group input[name]"
        )
    ).map((input) => input.name);

    const secondParentChildNames = Array.from(
        parentRows[1].querySelectorAll(
            ".df-repeatable-child-group input[name]"
        )
    ).map((input) => input.name);

    assert.deepEqual(firstParentChildNames, [
        "customers_0_contacts_0_name",
        "customers_0_contacts_0__id",
    ]);

    assert.deepEqual(secondParentChildNames, [
        "customers_1_contacts_0_name",
        "customers_1_contacts_0__id",
    ]);

    assert.equal(
        parentRows[1].querySelector(
            'input[name="customers_1_contacts_0_name"]'
        ).value,
        "Keep child"
    );

    assert.equal(
        parentRows[1].querySelector(
            'input[name="customers_1_contacts_0__id"]'
        ).value,
        "child-2"
    );

    assert.equal(
        parentRows[1].querySelectorAll(
            ".df-repeatable-child-group .df-repeatable-items > [data-repeatable-item]"
        ).length,
        1
    );

    dom.window.close();
});

test("adding a root row does not clone its nested child rows", async () => {
    const dom = new JSDOM(
        `
        <button id="df-notification-toggle" type="button" aria-expanded="false"></button>
        <div id="df-notification-menu" aria-hidden="true">
            <div id="df-notification-list"></div>
            <span id="df-notification-badge"></span>
            <span id="df-notification-menu-count"></span>
        </div>

        <form data-instance-id="1" data-edit-mode="1">
            <section class="df-repeatable-group" data-repeatable-group="parents">
                <div class="df-repeatable-items">
                    <div class="df-repeatable-item" data-repeatable-item>
                        <input name="parents_0_name" value="Parent">
                        <input type="hidden" name="parents_0__id" value="parent-1">
                        <section class="df-repeatable-group df-repeatable-child-group" data-repeatable-group="children">
                            <div class="df-repeatable-items">
                                <div class="df-repeatable-item" data-repeatable-item>
                                    <input name="parents_0_children_0_name" value="Child">
                                    <input type="hidden" name="parents_0_children_0__id" value="child-1">
                                </div>
                            </div>
                        </section>
                    </div>
                </div>
                <button type="button" class="df-repeatable-add" data-group-code="parents">
                    + افزودن
                </button>
            </section>
        </form>
        `,
        { url: "http://localhost/workflow/1/", runScripts: "outside-only" }
    );

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.CSS = dom.window.CSS || {};
    if (typeof globalThis.CSS.escape !== "function") {
        globalThis.CSS.escape = (value) =>
            String(value).replace(/[^a-zA-Z0-9_-]/g, (character) =>
                "\\" + character.codePointAt(0).toString(16) + " "
            );
    }
    globalThis.confirm = () => true;
    dom.window.confirm = () => true;
    globalThis.setTimeout = () => 0;
    globalThis.clearTimeout = () => {};

    class WebSocketStub {
        static OPEN = 1;
        static CONNECTING = 0;
        constructor() {
            this.readyState = WebSocketStub.OPEN;
        }
        addEventListener() {}
    }

    globalThis.WebSocket = WebSocketStub;
    dom.window.WebSocket = WebSocketStub;

    const namingPath = new URL(
        "../../operator_panel/static/operator_panel/js/repeatable-naming.js",
        import.meta.url
    );
    const namingSource = await readFile(namingPath, "utf8");
    dom.window.eval(namingSource);
    globalThis.reindexRepeatableFieldName =
        dom.window.DolphinFlowRepeatableNaming.reindexRepeatableFieldName;
    globalThis.buildRepeatableGroupPrefix =
        dom.window.DolphinFlowRepeatableNaming.buildRepeatableGroupPrefix;

    await import(`${appPath.href}?repeatable-root-clone-test`);
    document.dispatchEvent(
        new dom.window.Event("DOMContentLoaded", { bubbles: true })
    );

    document.querySelector(
        '.df-repeatable-add[data-group-code="parents"]'
    ).dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true })
    );

    const parentRows = document.querySelectorAll(
        '.df-repeatable-group[data-repeatable-group="parents"] > .df-repeatable-items > [data-repeatable-item]'
    );

    assert.equal(parentRows.length, 2);
    assert.equal(
        parentRows[1].querySelectorAll(
            '.df-repeatable-child-group .df-repeatable-items > [data-repeatable-item]'
        ).length,
        0
    );

    dom.window.close();
});


test("adding a child row does not clone its nested grandchild rows", async () => {
    const dom = new JSDOM(
        `
        <button id="df-notification-toggle" type="button" aria-expanded="false"></button>
        <div id="df-notification-menu" aria-hidden="true">
            <div id="df-notification-list"></div>
            <span id="df-notification-badge"></span>
            <span id="df-notification-menu-count"></span>
        </div>

        <form data-instance-id="1" data-edit-mode="1">
            <section class="df-repeatable-group" data-repeatable-group="parents">
                <div class="df-repeatable-items">
                    <div class="df-repeatable-item" data-repeatable-item>
                        <input name="parents_0_name" value="Parent">
                        <input type="hidden" name="parents_0__id" value="parent-1">
                        <section class="df-repeatable-group df-repeatable-child-group" data-repeatable-group="children">
                            <div class="df-repeatable-items">
                                <div class="df-repeatable-item" data-repeatable-item>
                                    <input name="parents_0_children_0_name" value="Child">
                                    <input type="hidden" name="parents_0_children_0__id" value="child-1">
                                    <section class="df-repeatable-group df-repeatable-child-group" data-repeatable-group="grandchildren">
                                        <div class="df-repeatable-items">
                                            <div class="df-repeatable-item" data-repeatable-item>
                                                <input name="parents_0_children_0_grandchildren_0_name" value="Grandchild">
                                                <input type="hidden" name="parents_0_children_0_grandchildren_0__id" value="grandchild-1">
                                            </div>
                                        </div>
                                    </section>
                                </div>
                            </div>
                            <button type="button" class="df-repeatable-add" data-group-code="children">
                                + افزودن
                            </button>
                        </section>
                    </div>
                </div>
            </section>
        </form>
        `,
        { url: "http://localhost/workflow/1/", runScripts: "outside-only" }
    );

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.CSS = dom.window.CSS || {};
    if (typeof globalThis.CSS.escape !== "function") {
        globalThis.CSS.escape = (value) =>
            String(value).replace(/[^a-zA-Z0-9_-]/g, (character) =>
                "\\" + character.codePointAt(0).toString(16) + " "
            );
    }
    globalThis.confirm = () => true;
    dom.window.confirm = () => true;
    globalThis.setTimeout = () => 0;
    globalThis.clearTimeout = () => {};

    class WebSocketStub {
        static OPEN = 1;
        static CONNECTING = 0;
        constructor() {
            this.readyState = WebSocketStub.OPEN;
        }
        addEventListener() {}
    }

    globalThis.WebSocket = WebSocketStub;
    dom.window.WebSocket = WebSocketStub;

    const namingPath = new URL(
        "../../operator_panel/static/operator_panel/js/repeatable-naming.js",
        import.meta.url
    );
    const namingSource = await readFile(namingPath, "utf8");
    dom.window.eval(namingSource);
    globalThis.reindexRepeatableFieldName =
        dom.window.DolphinFlowRepeatableNaming.reindexRepeatableFieldName;
    globalThis.buildRepeatableGroupPrefix =
        dom.window.DolphinFlowRepeatableNaming.buildRepeatableGroupPrefix;

    await import(`${appPath.href}?repeatable-child-clone-test`);
    document.dispatchEvent(
        new dom.window.Event("DOMContentLoaded", { bubbles: true })
    );

    document.querySelector(
        '.df-repeatable-add[data-group-code="children"]'
    ).dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true })
    );

    const parentRow = document.querySelector(
        '.df-repeatable-group[data-repeatable-group="parents"] > .df-repeatable-items > [data-repeatable-item]'
    );
    const childRows = parentRow.querySelectorAll(
        '.df-repeatable-child-group[data-repeatable-group="children"] > .df-repeatable-items > [data-repeatable-item]'
    );

    assert.equal(childRows.length, 2);
    assert.equal(
        childRows[1].querySelectorAll(
            '.df-repeatable-child-group[data-repeatable-group="grandchildren"] .df-repeatable-items > [data-repeatable-item]'
        ).length,
        0
    );

    dom.window.close();
});





test("deletes a flat TABLE child row without affecting its parent or sibling rows", async () => {
    const dom = new JSDOM(
        `
        <button id="df-notification-toggle" type="button" aria-expanded="false"></button>
        <div id="df-notification-menu" aria-hidden="true">
            <div id="df-notification-list"></div>
            <span id="df-notification-badge"></span>
            <span id="df-notification-menu-count"></span>
        </div>

        <form data-instance-id="1" data-edit-mode="1">
            <section
                class="df-repeatable-group df-table-group"
                data-repeatable-group="owners"
            >
                <div class="df-table-wrapper">
                    <table>
                        <tbody class="df-repeatable-items" data-group-code="owners">
                            <tr
                                class="df-repeatable-item df-repeatable-flat-row"
                                data-repeatable-item
                                data-repeatable-row-group="owners"
                                data-root-index="0"
                                data-row-path="owners_0"
                                data-row-id="root-1"
                                data-parent-row-id=""
                            >
                                <td class="df-table-actions">
                                    <button
                                        type="button"
                                        class="df-button df-repeatable-child-add"
                                        data-group-code="phones"
                                        data-parent-row-id="root-1"
                                    >+ افزودن</button>
                                </td>
                            </tr>

                            <tr
                                class="df-repeatable-item df-repeatable-flat-row df-repeatable-child-flat-row"
                                data-repeatable-item
                                data-repeatable-row-group="phones"
                                data-root-index="0"
                                data-row-path="owners_0_phones_0"
                                data-row-id="child-1"
                                data-parent-row-id="root-1"
                            >
                                <td>keep</td>
                                <td class="df-table-actions">
                                    <button
                                        type="button"
                                        class="df-button df-repeatable-delete"
                                        data-delete-label="شماره تماس"
                                        data-group-code="phones"
                                    >حذف</button>
                                </td>
                            </tr>

                            <tr
                                class="df-repeatable-item df-repeatable-flat-row df-repeatable-child-flat-row"
                                data-repeatable-item
                                data-repeatable-row-group="phones"
                                data-root-index="0"
                                data-row-path="owners_0_phones_1"
                                data-row-id="child-2"
                                data-parent-row-id="root-1"
                            >
                                <td>delete</td>
                                <td class="df-table-actions">
                                    <button
                                        type="button"
                                        class="df-button df-repeatable-delete"
                                        data-delete-label="شماره تماس"
                                        data-group-code="phones"
                                    >حذف</button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </section>
        </form>
        `,
        {
            url: "http://localhost/workflow/1/",
            runScripts: "outside-only",
        }
    );

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.CSS = dom.window.CSS || {};
    if (typeof globalThis.CSS.escape !== "function") {
        globalThis.CSS.escape = (value) =>
            String(value).replace(/[^a-zA-Z0-9_-]/g, (character) =>
                "\\" + character.codePointAt(0).toString(16) + " "
            );
    }
    globalThis.confirm = () => true;
    dom.window.confirm = () => true;
    globalThis.setTimeout = () => 0;
    globalThis.clearTimeout = () => {};

    class WebSocketStub {
        static OPEN = 1;
        static CONNECTING = 0;

        constructor() {
            this.readyState = WebSocketStub.OPEN;
        }

        addEventListener() {}
    }

    globalThis.WebSocket = WebSocketStub;
    dom.window.WebSocket = WebSocketStub;

    const namingPath = new URL(
        "../../operator_panel/static/operator_panel/js/repeatable-naming.js",
        import.meta.url
    );
    const namingSource = await readFile(namingPath, "utf8");
    dom.window.eval(namingSource);
    globalThis.reindexRepeatableFieldName =
        dom.window.DolphinFlowRepeatableNaming.reindexRepeatableFieldName;
    globalThis.buildRepeatableGroupPrefix =
        dom.window.DolphinFlowRepeatableNaming.buildRepeatableGroupPrefix;

    await import(`${appPath.href}?flat-table-delete-test`);

    document.dispatchEvent(
        new dom.window.Event("DOMContentLoaded", { bubbles: true })
    );

    const rows = document.querySelectorAll(
        ".df-table-group .df-repeatable-items > [data-repeatable-item]"
    );
    assert.equal(rows.length, 3);

    rows[2].querySelector(".df-repeatable-delete").dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true })
    );

    const remaining = document.querySelectorAll(
        ".df-table-group .df-repeatable-items tbody > [data-repeatable-item]"
    );

    assert.equal(remaining.length, 2);
    assert.ok(
        document.querySelector(
            '[data-repeatable-row-group="owners"][data-row-id="root-1"]'
        )
    );
    assert.ok(
        document.querySelector(
            '[data-repeatable-row-group="phones"][data-row-id="child-1"]'
        )
    );
    assert.equal(
        document.querySelector(
            '[data-repeatable-row-group="phones"][data-row-id="child-2"]'
        ),
        null
    );

    dom.window.close();
});


test("flat TABLE save after adding a child preserves four independent root payloads", async () => {
    const dom = new JSDOM(
        `
        <button id="df-notification-toggle" type="button" aria-expanded="false"></button>
        <div id="df-notification-menu" aria-hidden="true">
            <div id="df-notification-list"></div>
            <span id="df-notification-badge"></span>
            <span id="df-notification-menu-count"></span>
        </div>

        <form data-instance-id="1" data-edit-mode="1">
            <section
                class="df-repeatable-group df-table-group"
                data-repeatable-group="parts"
            >
                <div class="df-table-wrapper">
                    <table>
                        <tbody class="df-repeatable-items" data-group-code="parts">
                            <tr
                                class="df-repeatable-flat-template"
                                data-repeatable-item
                                data-repeatable-template
                                data-repeatable-root-template
                                style="display:none;"
                            >
                                <td>
                                    <input name="parts_TEMPLATE_OwnerName" value="">
                                    <input name="parts_TEMPLATE_OwnerAddress" value="">
                                </td>
                                <td class="df-table-actions">
                                    <button
                                        type="button"
                                        class="df-repeatable-child-add"
                                        data-group-code="child_parts"
                                        data-parent-row-id=""
                                    >+ افزودن</button>
                                </td>
                            </tr>

                            <tr
                                class="df-repeatable-flat-template"
                                data-repeatable-item
                                data-repeatable-template
                                data-repeatable-child-template
                                data-child-group-code="child_parts"
                                style="display:none;"
                            >
                                <td></td>
                                <td>
                                    <input
                                        name="PARENT_PREFIXchild_parts_TEMPLATE_Phone"
                                        value=""
                                    >
                                </td>
                                <td class="df-table-actions">
                                    <input
                                        type="hidden"
                                        name="PARENT_PREFIXchild_parts_TEMPLATE__id"
                                        value=""
                                    >
                                </td>
                            </tr>

                            <tr
                                class="df-repeatable-item df-repeatable-flat-row"
                                data-repeatable-item
                                data-repeatable-row-group="child_parts"
                                data-root-index="0"
                                data-row-path="parts_0_child_parts_0"
                                data-row-id="child-0"
                                data-parent-row-id="root-0"
                            >
                                <td>
                                    <input
                                        name="parts_0_OwnerName"
                                        value="علی"
                                    >
                                    <input
                                        name="parts_0_OwnerAddress"
                                        value="تهران"
                                    >
                                    <input
                                        type="hidden"
                                        name="parts_0__id"
                                        value="root-0"
                                    >
                                </td>
                                <td>
                                    <input
                                        name="parts_0_child_parts_0_Phone"
                                        value="09110000000"
                                    >
                                </td>
                                <td class="df-table-actions">
                                    <button
                                        type="button"
                                        class="df-repeatable-child-add"
                                        data-group-code="child_parts"
                                        data-parent-row-id="root-0"
                                    >+ افزودن</button>
                                </td>
                            </tr>

                            <tr
                                class="df-repeatable-item df-repeatable-flat-row"
                                data-repeatable-item
                                data-repeatable-row-group="child_parts"
                                data-root-index="1"
                                data-row-path="parts_1_child_parts_0"
                                data-row-id="child-1"
                                data-parent-row-id="root-1"
                            >
                                <td>
                                    <input
                                        name="parts_1_OwnerName"
                                        value="سعید"
                                    >
                                    <input
                                        name="parts_1_OwnerAddress"
                                        value="تهران نیست"
                                    >
                                    <input
                                        type="hidden"
                                        name="parts_1__id"
                                        value="root-1"
                                    >
                                </td>
                                <td>
                                    <input
                                        name="parts_1_child_parts_0_Phone"
                                        value="09120000000"
                                    >
                                </td>
                                <td class="df-table-actions">
                                    <button
                                        type="button"
                                        class="df-repeatable-child-add"
                                        data-group-code="child_parts"
                                        data-parent-row-id="root-1"
                                    >+ افزودن</button>
                                </td>
                            </tr>

                            <tr
                                class="df-repeatable-item df-repeatable-flat-row"
                                data-repeatable-item
                                data-repeatable-row-group="child_parts"
                                data-root-index="2"
                                data-row-path="parts_2_child_parts_0"
                                data-row-id="child-2"
                                data-parent-row-id="root-2"
                            >
                                <td>
                                    <input
                                        name="parts_2_OwnerName"
                                        value="رضا"
                                    >
                                    <input
                                        name="parts_2_OwnerAddress"
                                        value="اصفهان"
                                    >
                                    <input
                                        type="hidden"
                                        name="parts_2__id"
                                        value="root-2"
                                    >
                                </td>
                                <td>
                                    <input
                                        name="parts_2_child_parts_0_Phone"
                                        value="09130000000"
                                    >
                                </td>
                                <td class="df-table-actions">
                                    <button
                                        type="button"
                                        class="df-repeatable-child-add"
                                        data-group-code="child_parts"
                                        data-parent-row-id="root-2"
                                    >+ افزودن</button>
                                </td>
                            </tr>

                            <tr
                                class="df-repeatable-item df-repeatable-flat-row"
                                data-repeatable-item
                                data-repeatable-row-group="child_parts"
                                data-root-index="3"
                                data-row-path="parts_3_child_parts_0"
                                data-row-id="child-3"
                                data-parent-row-id="root-3"
                            >
                                <td>
                                    <input
                                        name="parts_3_OwnerName"
                                        value="مریم"
                                    >
                                    <input
                                        name="parts_3_OwnerAddress"
                                        value="شیراز"
                                    >
                                    <input
                                        type="hidden"
                                        name="parts_3__id"
                                        value="root-3"
                                    >
                                </td>
                                <td>
                                    <input
                                        name="parts_3_child_parts_0_Phone"
                                        value="09140000000"
                                    >
                                </td>
                                <td class="df-table-actions">
                                    <button
                                        type="button"
                                        class="df-repeatable-child-add"
                                        data-group-code="child_parts"
                                        data-parent-row-id="root-3"
                                    >+ افزودن</button>
                                </td>
                            </tr>
                        </tbody>
                    </table>
                </div>
            </section>
        </form>
        `,
        {
            url: "http://localhost/workflow/1/",
            runScripts: "outside-only",
        }
    );

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.CSS = dom.window.CSS || {};
    if (typeof globalThis.CSS.escape !== "function") {
        globalThis.CSS.escape = (value) =>
            String(value).replace(/[^a-zA-Z0-9_-]/g, (character) =>
                "\\" + character.codePointAt(0).toString(16) + " "
            );
    }
    globalThis.confirm = () => true;
    dom.window.confirm = () => true;
    globalThis.setTimeout = () => 0;
    globalThis.clearTimeout = () => {};

    class WebSocketStub {
        static OPEN = 1;
        static CONNECTING = 0;

        constructor() {
            this.readyState = WebSocketStub.OPEN;
        }

        addEventListener() {}
    }

    globalThis.WebSocket = WebSocketStub;
    dom.window.WebSocket = WebSocketStub;

    const namingPath = new URL(
        "../../operator_panel/static/operator_panel/js/repeatable-naming.js",
        import.meta.url
    );
    const namingSource = await readFile(namingPath, "utf8");
    dom.window.eval(namingSource);
    globalThis.reindexRepeatableFieldName =
        dom.window.DolphinFlowRepeatableNaming.reindexRepeatableFieldName;
    globalThis.buildRepeatableGroupPrefix =
        dom.window.DolphinFlowRepeatableNaming.buildRepeatableGroupPrefix;

    await import(`${appPath.href}?flat-table-save-four-roots-test`);

    document.dispatchEvent(
        new dom.window.Event("DOMContentLoaded", { bubbles: true })
    );

    const rootRows = Array.from(
        document.querySelectorAll(
            '.df-table-group [data-repeatable-item][data-repeatable-row-group="child_parts"]'
        )
    );

    assert.equal(rootRows.length, 4);

    /*
     * This is the exact production interaction:
     * click Add Child on the first root's visual child row.
     */
    rootRows[0].querySelector(
        '.df-repeatable-child-add[data-parent-row-id="root-0"]'
    ).dispatchEvent(
        new dom.window.MouseEvent("click", { bubbles: true })
    );

    /*
     * The problem is observed only when Save serializes the form.
     * Build the same native FormData payload that a browser submits.
     */
    const form = document.querySelector("form");
    const formData = new dom.window.FormData(form);
    const entries = Array.from(formData.entries());

    const valuesByName = new Map();
    for (const [name, value] of entries) {
        const values = valuesByName.get(name) || [];
        values.push(value);
        valuesByName.set(name, values);
    }

    assert.deepEqual(valuesByName.get("parts_0_OwnerName"), ["علی"]);
    assert.deepEqual(valuesByName.get("parts_1_OwnerName"), ["سعید"]);
    assert.deepEqual(valuesByName.get("parts_2_OwnerName"), ["رضا"]);
    assert.deepEqual(valuesByName.get("parts_3_OwnerName"), ["مریم"]);

    assert.deepEqual(valuesByName.get("parts_0_OwnerAddress"), ["تهران"]);
    assert.deepEqual(valuesByName.get("parts_1_OwnerAddress"), ["تهران نیست"]);
    assert.deepEqual(valuesByName.get("parts_2_OwnerAddress"), ["اصفهان"]);
    assert.deepEqual(valuesByName.get("parts_3_OwnerAddress"), ["شیراز"]);

    assert.deepEqual(valuesByName.get("parts_0__id"), ["root-0"]);
    assert.deepEqual(valuesByName.get("parts_1__id"), ["root-1"]);
    assert.deepEqual(valuesByName.get("parts_2__id"), ["root-2"]);
    assert.deepEqual(valuesByName.get("parts_3__id"), ["root-3"]);

    assert.deepEqual(valuesByName.get("parts_0_child_parts_0_Phone"), ["09110000000"]);
    assert.deepEqual(valuesByName.get("parts_1_child_parts_0_Phone"), ["09120000000"]);
    assert.deepEqual(valuesByName.get("parts_2_child_parts_0_Phone"), ["09130000000"]);
    assert.deepEqual(valuesByName.get("parts_3_child_parts_0_Phone"), ["09140000000"]);

    assert.ok(
        valuesByName.has("parts_0_child_parts_1_Phone"),
        "the newly added child must be present in the saved FormData"
    );

    assert.equal(
        valuesByName.get("parts_0_child_parts_1_Phone")[0],
        "",
    );

    /*
     * The root fields must occur exactly once in the serialized payload.
     * Duplicate names here are what Django QueryDict turns into arrays
     * such as ['علی', 'سعید'].
     */
    for (const name of [
        "parts_0_OwnerName",
        "parts_1_OwnerName",
        "parts_2_OwnerName",
        "parts_3_OwnerName",
        "parts_0_OwnerAddress",
        "parts_1_OwnerAddress",
        "parts_2_OwnerAddress",
        "parts_3_OwnerAddress",
        "parts_0__id",
        "parts_1__id",
        "parts_2__id",
        "parts_3__id",
    ]) {
        assert.equal(
            valuesByName.get(name).length,
            1,
            `saved FormData must contain exactly one value for ${name}`,
        );
    }

    dom.window.close();
});
