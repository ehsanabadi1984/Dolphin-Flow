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
    globalThis.CSS = dom.window.CSS;
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
    globalThis.CSS = dom.window.CSS;
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
    globalThis.CSS = dom.window.CSS;
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
    globalThis.CSS = dom.window.CSS;
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
                <div class="df-repeatable-items">
                    <table>
                        <tbody>
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
    globalThis.CSS = dom.window.CSS;
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
        ".df-table-group .df-repeatable-items tbody > [data-repeatable-item]"
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
