import assert from "node:assert/strict";
import { test } from "node:test";
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
        { url: "http://localhost/workflow/1/" }
    );

    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.CSS = dom.window.CSS;
    globalThis.confirm = () => true;

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

    await import(appPath);

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
});
